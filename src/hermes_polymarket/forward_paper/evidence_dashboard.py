"""Evidence dashboard for accumulated forward-paper campaigns."""

from __future__ import annotations

import glob
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def expand_db_globs(patterns: list[str]) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        paths.extend(matches if matches else [pattern])
    return list(dict.fromkeys(paths))


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _threshold(run: dict[str, Any]) -> str:
    config = _loads(run.get("config_json"), {})
    value = config.get("min_move_pct")
    return str(value) if value is not None else "unknown"


def _add_bucket(bucket: dict[str, Any], *, signals: int = 0, positions: int = 0, closed: int = 0, pnl: float = 0.0) -> None:
    bucket["signals"] += signals
    bucket["positions"] += positions
    bucket["closed_positions"] += closed
    bucket["net_pnl"] += pnl


def evidence_dashboard(db_paths: list[str | Path], *, include_fixture: bool = False) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []

    for raw_path in db_paths:
        db_path = str(raw_path)
        if not Path(db_path).exists():
            continue
        conn = _connect(db_path)
        try:
            if not all(
                _has_table(conn, name)
                for name in ("forward_paper_runs", "forward_paper_signals", "forward_paper_positions")
            ):
                continue
            run_where = "" if include_fixture else "WHERE fixture = 0"
            run_rows = [dict(row) | {"db": db_path} for row in conn.execute(f"SELECT * FROM forward_paper_runs {run_where}")]
            run_thresholds = {row["run_id"]: _threshold(row) for row in run_rows}
            runs.extend(run_rows)

            signal_where = "" if include_fixture else "WHERE fixture = 0"
            for row in conn.execute(f"SELECT * FROM forward_paper_signals {signal_where}"):
                data = dict(row)
                data["db"] = db_path
                data["threshold"] = run_thresholds.get(data["run_id"], "unknown")
                signals.append(data)

            position_where = "" if include_fixture else "WHERE fixture = 0"
            for row in conn.execute(f"SELECT * FROM forward_paper_positions {position_where}"):
                data = dict(row)
                data["db"] = db_path
                data["threshold"] = run_thresholds.get(data["run_id"], "unknown")
                positions.append(data)
        finally:
            conn.close()

    closed_positions = [row for row in positions if row.get("status") == "closed"]
    by_threshold: dict[str, dict[str, Any]] = defaultdict(lambda: {"signals": 0, "positions": 0, "closed_positions": 0, "net_pnl": 0.0, "warnings": []})
    by_symbol: dict[str, dict[str, Any]] = defaultdict(lambda: {"signals": 0, "positions": 0, "closed_positions": 0, "net_pnl": 0.0, "warnings": []})
    by_run: dict[str, dict[str, Any]] = {}

    for run in runs:
        by_run[run["run_id"]] = {"signals": 0, "positions": 0, "closed_positions": 0, "net_pnl": 0.0, "db": run["db"]}

    for signal in signals:
        by_threshold[signal["threshold"]]["signals"] += 1
        by_symbol[str(signal.get("symbol") or "unknown")]["signals"] += 1
        by_run.setdefault(signal["run_id"], {"signals": 0, "positions": 0, "closed_positions": 0, "net_pnl": 0.0, "db": signal["db"]})["signals"] += 1

    for position in positions:
        threshold = str(position.get("threshold") or "unknown")
        symbol = str(position.get("symbol") or "unknown")
        pnl = float(position.get("net_pnl") or 0.0) if position.get("status") == "closed" else 0.0
        closed = int(position.get("status") == "closed")
        _add_bucket(by_threshold[threshold], positions=1, closed=closed, pnl=pnl)
        _add_bucket(by_symbol[symbol], positions=1, closed=closed, pnl=pnl)
        _add_bucket(by_run.setdefault(position["run_id"], {"signals": 0, "positions": 0, "closed_positions": 0, "net_pnl": 0.0, "db": position["db"]}), positions=1, closed=closed, pnl=pnl)

    for threshold, bucket in by_threshold.items():
        if threshold != "unknown":
            try:
                if float(threshold) < 0.03:
                    bucket["warnings"].append("exploratory_threshold")
            except ValueError:
                pass
        if bucket["closed_positions"] < 20:
            bucket["warnings"].append("small_sample")

    reject_by_symbol = Counter(
        f"{signal.get('symbol')}:{signal.get('final_action')}:{signal.get('risk_reason')}"
        for signal in signals
        if signal.get("final_action") != "paper_fill"
    )
    for symbol, bucket in by_symbol.items():
        symbol_rejects = {key: count for key, count in reject_by_symbol.items() if key.startswith(f"{symbol}:")}
        if any("thin_depth" in key for key in symbol_rejects):
            bucket["warnings"].append("thin_depth_2pct_seen")
        if any("wide_spread" in key for key in symbol_rejects):
            bucket["warnings"].append("wide_spread_seen")
        if bucket["closed_positions"] < 20:
            bucket["warnings"].append("small_sample")

    dominance = dominance_report(list(by_run.values()), closed_positions)
    readiness = {
        "ready_for_diagnostic_arena": len(closed_positions) >= 5 or len(signals) >= 30,
        "ready_for_strategy_claim": (
            len(signals) >= 50
            and len(closed_positions) >= 20
            and sum(float(row.get("net_pnl") or 0.0) for row in closed_positions) > 0
            and not dominance["one_run_dominance"]
            and not dominance["one_trade_effect"]
        ),
        "ready_for_live_review": False,
    }

    return {
        "mode": "forward_paper_evidence_dashboard",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "dbs": [str(path) for path in db_paths if Path(path).exists()],
        "total_runs": len(runs),
        "total_signals": len(signals),
        "total_positions": len(positions),
        "closed_positions": len(closed_positions),
        "net_pnl": sum(float(row.get("net_pnl") or 0.0) for row in closed_positions),
        "by_threshold": dict(by_threshold),
        "by_symbol": dict(by_symbol),
        "dominance": dominance,
        "readiness": readiness,
        "recommendation": "Collect more data; do not live trade.",
    }


def dominance_report(run_buckets: list[dict[str, Any]], closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    total_pnl = sum(float(row.get("net_pnl") or 0.0) for row in closed_positions)
    max_run_pnl = max((abs(float(row.get("net_pnl") or 0.0)) for row in run_buckets), default=0.0)
    max_trade_pnl = max((abs(float(row.get("net_pnl") or 0.0)) for row in closed_positions), default=0.0)
    return {
        "one_run_dominance": bool(total_pnl and max_run_pnl / abs(total_pnl) > 0.5),
        "one_trade_effect": bool(total_pnl and max_trade_pnl / abs(total_pnl) > 0.5),
        "max_abs_run_pnl": max_run_pnl,
        "max_abs_trade_pnl": max_trade_pnl,
    }


def write_evidence_dashboard(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path
