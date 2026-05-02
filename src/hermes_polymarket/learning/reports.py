"""Learning reports."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.storage.db import Database


def daily_report(db: Database) -> dict[str, Any]:
    health = [dict(row) for row in db.source_health()]
    signal_counts = _count_by(db, "signal_decisions", "final_action")
    reject_counts = _count_by(db, "signal_decisions", "risk_reason")
    return {
        "source_health": health,
        "signals": {
            "total": _count(db, "signal_decisions"),
            "by_final_action": signal_counts,
            "rejected_by_reason": reject_counts,
        },
        "paper_pnl": {
            "status": "not_computed_no_exit_model",
            "by_strategy": {},
            "by_category": {},
            "by_wallet": {},
        },
        "experiments": {
            "recent": [_experiment_row(row) for row in db.conn.execute("SELECT * FROM strategy_experiments ORDER BY started_at DESC LIMIT 10")],
            "total": _count(db, "strategy_experiments"),
        },
        "wallet_replay": {
            "recent_runs": [_replay_run_row(row) for row in db.conn.execute("SELECT * FROM wallet_replay_runs ORDER BY created_at DESC LIMIT 10")],
            "total_runs": _count(db, "wallet_replay_runs"),
        },
        "execution_quality": {
            "average_slippage": 0.0,
            "fill_rate": 0.0,
        },
        "lessons": [],
        "hypotheses": [dict(row) for row in db.conn.execute("SELECT * FROM hypotheses ORDER BY created_at DESC LIMIT 20")],
        "safety": {
            "live_trading_enabled": False,
            "anomalies": [],
        },
    }


def weekly_review(db: Database) -> dict[str, Any]:
    report = daily_report(db)
    report["review_actions"] = {
        "retire_bad_rules": [],
        "promote_to_paper_candidates": [],
        "overfit_warnings": [],
    }
    return report


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def _count(db: Database, table: str) -> int:
    return int(db.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])


def _count_by(db: Database, table: str, column: str) -> dict[str, int]:
    rows = db.conn.execute(f"SELECT {column} AS k, COUNT(*) AS n FROM {table} GROUP BY {column}").fetchall()
    return {str(row["k"] or "unknown"): int(row["n"]) for row in rows}


def _experiment_row(row: Any) -> dict[str, Any]:
    metrics = json.loads(row["metrics_json"] or "{}")
    return {
        "run_id": row["run_id"],
        "run_type": row["run_type"],
        "strategy_id": row["strategy_id"],
        "data_quality": row["data_quality"],
        "replayed_trades": metrics.get("replayed_trades"),
        "pending_trades": metrics.get("pending_trades"),
        "quality_warnings": (metrics.get("quality") or {}).get("warnings", []),
    }


def _replay_run_row(row: Any) -> dict[str, Any]:
    metrics = json.loads(row["metrics_json"] or "{}")
    return {
        "run_id": row["run_id"],
        "wallet": row["wallet"],
        "mode": row["mode"],
        "data_quality": row["data_quality"],
        "observed_trades": metrics.get("observed_trades"),
        "replayed_trades": metrics.get("replayed_trades"),
        "pending_trades": metrics.get("pending_trades"),
        "skipped_trades_by_reason": metrics.get("skipped_trades_by_reason", {}),
        "quality_warnings": (metrics.get("quality") or {}).get("warnings", []),
    }
