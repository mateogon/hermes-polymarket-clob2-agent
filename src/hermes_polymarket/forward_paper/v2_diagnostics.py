"""Diagnostics for persisted Campaign v2 forward-paper signals."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _reason(payload: dict[str, Any], section: str, fallback: str | None = None) -> str:
    value = payload.get(section)
    if isinstance(value, dict):
        reason = value.get("decision") if section == "fair_value" else value.get("reason")
        if reason:
            return str(reason)
    if section == "fair_value":
        legacy = payload.get("strike_fair_value")
        if isinstance(legacy, dict):
            decision = legacy.get("fair_value_decision")
            if decision:
                return str(decision)
            reason = legacy.get("fair_value_reason")
            if reason:
                return str(reason)
    return fallback or "missing"


def v2_diagnostics(
    *,
    db_path: str | Path,
    run_id: str | None = None,
    include_fixture: bool = False,
) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        if not _has_table(conn, "forward_paper_signals"):
            return {
                "mode": "v2_signal_diagnostics",
                "db": str(db_path),
                "run_id": run_id,
                "signals": 0,
                "positions": 0,
                "fair_value_reasons": {},
                "stale_quote_reasons": {},
                "market_score_reasons": {},
                "risk_reasons": {},
                "warnings": ["missing_forward_paper_signals_table"],
            }
        clauses: list[str] = []
        values: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            values.append(run_id)
        if not include_fixture:
            clauses.append("fixture = 0")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(f"SELECT * FROM forward_paper_signals {where}", values).fetchall()

        positions = 0
        if _has_table(conn, "forward_paper_positions"):
            pos_clauses = list(clauses)
            pos_values = list(values)
            pos_where = "WHERE " + " AND ".join(pos_clauses) if pos_clauses else ""
            positions = int(conn.execute(f"SELECT COUNT(*) AS n FROM forward_paper_positions {pos_where}", pos_values).fetchone()["n"])

        fair = Counter()
        stale = Counter()
        market_score = Counter()
        risk = Counter()
        missing_payload_sections = 0
        for row in rows:
            payload = _loads(row["payload_json"])
            if not all(isinstance(payload.get(section), dict) for section in ("fair_value", "stale_quote", "market_score", "risk")):
                missing_payload_sections += 1
            fair[_reason(payload, "fair_value", row["risk_reason"])] += 1
            stale[_reason(payload, "stale_quote")] += 1
            score = payload.get("market_score")
            if isinstance(score, dict):
                decision = score.get("decision")
                if decision:
                    market_score[str(decision)] += 1
                for reason in score.get("reasons") or []:
                    market_score[str(reason)] += 1
            else:
                market_score["missing"] += 1
            risk[_reason(payload, "risk", row["risk_reason"])] += 1

        warnings: list[str] = []
        if missing_payload_sections:
            warnings.append("old_or_partial_payload_fields_seen")
        return {
            "mode": "v2_signal_diagnostics",
            "db": str(db_path),
            "run_id": run_id,
            "signals": len(rows),
            "positions": positions,
            "fair_value_reasons": dict(fair),
            "stale_quote_reasons": dict(stale),
            "market_score_reasons": dict(market_score),
            "risk_reasons": dict(risk),
            "warnings": warnings,
        }
    finally:
        conn.close()
