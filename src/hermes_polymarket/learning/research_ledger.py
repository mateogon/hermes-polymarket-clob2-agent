"""Research hypothesis ledger on top of the learning tables."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.storage.db import Database


def upsert_hypothesis(
    db: Database,
    *,
    hypothesis_id: str,
    strategy: str,
    market_family: str,
    claim: str,
    status: str,
    data_quality: str,
    evidence: dict[str, Any] | None = None,
    next_action: str = "",
    proposed_test: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_payload = {
        "strategy": strategy,
        "market_family": market_family,
        "data_quality": data_quality,
        "evidence": evidence or {},
    }
    proposed_payload = {
        "strategy": strategy,
        "market_family": market_family,
        "next_action": next_action,
        "proposed_test": proposed_test or {},
    }
    result_payload = result or {}
    db.conn.execute(
        """
        INSERT OR REPLACE INTO hypotheses
          (hypothesis_id, statement, status, evidence_json, proposed_test_json, result_json, promoted_rule_id)
        VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT promoted_rule_id FROM hypotheses WHERE hypothesis_id = ?), NULL))
        """,
        (
            hypothesis_id,
            claim,
            status,
            json.dumps(evidence_payload, sort_keys=True),
            json.dumps(proposed_payload, sort_keys=True),
            json.dumps(result_payload, sort_keys=True),
            hypothesis_id,
        ),
    )
    db.conn.commit()
    row = db.conn.execute("SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)).fetchone()
    return normalize_hypothesis(dict(row)) if row else {}


def update_hypothesis(
    db: Database,
    *,
    hypothesis_id: str,
    status: str | None = None,
    evidence: dict[str, Any] | None = None,
    next_action: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    row = db.conn.execute("SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)).fetchone()
    if row is None:
        return None
    current = dict(row)
    evidence_payload = _loads(current.get("evidence_json"), {})
    proposed_payload = _loads(current.get("proposed_test_json"), {})
    result_payload = _loads(current.get("result_json"), {})
    if evidence is not None:
        existing_evidence = evidence_payload.get("evidence") if isinstance(evidence_payload.get("evidence"), dict) else {}
        evidence_payload["evidence"] = {**existing_evidence, **evidence}
    if next_action is not None:
        proposed_payload["next_action"] = next_action
    if result is not None:
        result_payload = {**result_payload, **result}
    db.conn.execute(
        """
        UPDATE hypotheses
        SET status = ?, evidence_json = ?, proposed_test_json = ?, result_json = ?
        WHERE hypothesis_id = ?
        """,
        (
            status or current["status"],
            json.dumps(evidence_payload, sort_keys=True),
            json.dumps(proposed_payload, sort_keys=True),
            json.dumps(result_payload, sort_keys=True),
            hypothesis_id,
        ),
    )
    db.conn.commit()
    row = db.conn.execute("SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)).fetchone()
    return normalize_hypothesis(dict(row)) if row else None


def list_hypotheses(db: Database, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if status:
        rows = db.conn.execute("SELECT * FROM hypotheses WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
    else:
        rows = db.conn.execute("SELECT * FROM hypotheses ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [normalize_hypothesis(dict(row)) for row in rows]


def get_hypothesis(db: Database, hypothesis_id: str) -> dict[str, Any] | None:
    row = db.conn.execute("SELECT * FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)).fetchone()
    return normalize_hypothesis(dict(row)) if row else None


def experiment_report(db: Database, *, limit: int = 20) -> dict[str, Any]:
    rows = db.conn.execute("SELECT * FROM strategy_experiments ORDER BY COALESCE(ended_at, started_at, run_id) DESC LIMIT ?", (limit,)).fetchall()
    experiments = []
    for row in rows:
        data = dict(row)
        experiments.append(
            {
                "run_id": data["run_id"],
                "run_type": data["run_type"],
                "strategy_id": data["strategy_id"],
                "data_quality": data["data_quality"],
                "dataset_version": data["dataset_version"],
                "parameters": _loads(data["parameters_json"], {}),
                "metrics": _loads(data["metrics_json"], {}),
                "artifacts": _loads(data["artifacts_json"], {}),
                "started_at": data["started_at"],
                "ended_at": data["ended_at"],
            }
        )
    return {
        "experiments": experiments,
        "hypotheses": list_hypotheses(db, limit=limit),
    }


def normalize_hypothesis(row: dict[str, Any]) -> dict[str, Any]:
    evidence = _loads(row.get("evidence_json"), {})
    proposed = _loads(row.get("proposed_test_json"), {})
    result = _loads(row.get("result_json"), {})
    return {
        "hypothesis_id": row["hypothesis_id"],
        "strategy": evidence.get("strategy") or proposed.get("strategy"),
        "market_family": evidence.get("market_family") or proposed.get("market_family"),
        "claim": row["statement"],
        "status": row["status"],
        "data_quality": evidence.get("data_quality"),
        "evidence": evidence.get("evidence", evidence),
        "next_action": proposed.get("next_action"),
        "proposed_test": proposed.get("proposed_test", proposed),
        "result": result,
        "promoted_rule_id": row.get("promoted_rule_id"),
        "created_at": row.get("created_at"),
    }


def _loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default
