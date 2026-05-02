"""Campaign-level summaries across isolated forward-paper databases."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
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


def _load_list(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _threshold_from_run(run: sqlite3.Row) -> float | str:
    config = _loads(run["config_json"])
    value = config.get("min_move_pct")
    if value is None:
        return "unknown"
    try:
        return float(value)
    except (TypeError, ValueError):
        return "unknown"


def _top(counter: Counter[str], limit: int = 10) -> dict[str, int]:
    return {key: value for key, value in counter.most_common(limit)}


def _warnings(run: sqlite3.Row, signals: int, positions: int, threshold: float | str) -> list[str]:
    quality = _loads(run["quality_json"])
    warnings = list(quality.get("warnings") or [])
    if isinstance(threshold, float) and threshold < 0.03 and "exploratory_threshold" not in warnings:
        warnings.append("exploratory_threshold")
    if signals < 30 and "small_signal_sample" not in warnings:
        warnings.append("small_signal_sample")
    if positions < 20 and "small_position_sample" not in warnings:
        warnings.append("small_position_sample")
    return warnings


def summarize_campaign_dbs(
    db_paths: list[str | Path],
    *,
    include_fixture: bool = False,
    include_signals: bool = False,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    threshold_matrix: dict[str, dict[str, Any]] = defaultdict(lambda: {"signals": 0, "positions": 0, "closed": 0, "net_pnl": 0.0})
    symbol_matrix: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "signals": 0,
            "positions": 0,
            "closed": 0,
            "net_pnl": 0.0,
            "actions": Counter(),
            "rejects": Counter(),
        }
    )

    for raw_path in db_paths:
        db_path = str(raw_path)
        conn = _connect(db_path)
        try:
            run_rows = conn.execute(
                f"""
                SELECT *
                FROM forward_paper_runs
                {'' if include_fixture else 'WHERE fixture = 0'}
                ORDER BY started_at ASC
                """
            ).fetchall()
            for run in run_rows:
                run_id = str(run["run_id"])
                threshold = _threshold_from_run(run)
                threshold_key = str(threshold)
                symbols = [str(item) for item in _load_list(run["symbols_json"])]
                report = _loads(run["report_json"])
                summary = _loads(run["summary_json"])

                signal_clause = "run_id = ?"
                values: list[Any] = [run_id]
                if not include_fixture:
                    signal_clause += " AND fixture = 0"
                signal_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM forward_paper_signals
                    WHERE {signal_clause}
                    ORDER BY created_at ASC
                    """,
                    values,
                ).fetchall()

                position_clause = "run_id = ?"
                position_values: list[Any] = [run_id]
                if not include_fixture:
                    position_clause += " AND fixture = 0"
                position_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM forward_paper_positions
                    WHERE {position_clause}
                    ORDER BY entry_ts_ms ASC
                    """,
                    position_values,
                ).fetchall()

                reject_counter: Counter[str] = Counter()
                action_counter: Counter[str] = Counter()
                by_symbol_counter: Counter[str] = Counter()
                for signal in signal_rows:
                    symbol = str(signal["symbol"])
                    action_key = f"{signal['final_action']}:{signal['risk_reason']}"
                    symbol_action_key = f"{symbol}:{signal['final_action']}:{signal['risk_reason']}"
                    action_counter[action_key] += 1
                    by_symbol_counter[symbol_action_key] += 1
                    if signal["final_action"] != "paper_fill":
                        reject_counter[symbol_action_key] += 1
                    symbol_state = symbol_matrix[symbol]
                    symbol_state["signals"] += 1
                    symbol_state["actions"][action_key] += 1
                    if signal["final_action"] != "paper_fill":
                        symbol_state["rejects"][f"{signal['final_action']}:{signal['risk_reason']}"] += 1

                for pos in position_rows:
                    symbol = str(pos["symbol"])
                    symbol_state = symbol_matrix[symbol]
                    symbol_state["positions"] += 1
                    if pos["status"] == "closed":
                        symbol_state["closed"] += 1
                        symbol_state["net_pnl"] += float(pos["net_pnl"] or 0.0)

                positions = int(report.get("positions") or len(position_rows))
                closed = int(report.get("closed") or sum(1 for row in position_rows if row["status"] == "closed"))
                net_pnl = float(report.get("net_pnl") or sum(float(row["net_pnl"] or 0.0) for row in position_rows if row["status"] == "closed"))
                signals = int(report.get("signals") or len(signal_rows))

                threshold_state = threshold_matrix[threshold_key]
                threshold_state["signals"] += signals
                threshold_state["positions"] += positions
                threshold_state["closed"] += closed
                threshold_state["net_pnl"] += net_pnl

                run_out = {
                    "db": db_path,
                    "run_id": run_id,
                    "threshold": threshold,
                    "symbols": symbols,
                    "signals": signals,
                    "positions": positions,
                    "closed": closed,
                    "net_pnl": net_pnl,
                    "latency_events": int(summary.get("latency_events") or 0),
                    "paper_opportunities": int(summary.get("paper_opportunities") or 0),
                    "fills_simulated": int(summary.get("fills_simulated") or 0),
                    "risk_rejected": int(summary.get("risk_rejected") or 0),
                    "top_actions": _top(action_counter),
                    "top_rejects": _top(reject_counter),
                    "warnings": _warnings(run, signals, positions, threshold),
                }
                if include_signals:
                    run_out["signals_sample"] = [dict(row) for row in signal_rows[:100]]
                runs.append(run_out)
        finally:
            conn.close()

    matrix_by_symbol: dict[str, Any] = {}
    for symbol, state in symbol_matrix.items():
        actions: Counter[str] = state.pop("actions")
        rejects: Counter[str] = state.pop("rejects")
        matrix_by_symbol[symbol] = {
            **state,
            "top_action": actions.most_common(1)[0][0] if actions else None,
            "top_reject": rejects.most_common(1)[0][0] if rejects else None,
            "actions": _top(actions),
            "rejects": _top(rejects),
        }

    return {
        "mode": "forward_paper_campaign_summary",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "runs": runs,
        "matrix_by_threshold": dict(threshold_matrix),
        "matrix_by_symbol": matrix_by_symbol,
        "recommendations": campaign_recommendations(runs, matrix_by_symbol),
    }


def campaign_recommendations(runs: list[dict[str, Any]], matrix_by_symbol: dict[str, Any]) -> list[str]:
    recommendations = ["Do not use this as live-trading evidence.", "Do not loosen RiskManager thresholds yet."]
    thresholds_with_positions = [run["threshold"] for run in runs if int(run.get("positions") or 0) > 0]
    if thresholds_with_positions:
        recommendations.append(f"Collect more windows for thresholds with positions: {sorted({str(t) for t in thresholds_with_positions})}.")
    zero_signal_thresholds = [run["threshold"] for run in runs if int(run.get("signals") or 0) == 0]
    if zero_signal_thresholds:
        recommendations.append(f"Treat thresholds with zero signals as inactive for calm windows: {sorted({str(t) for t in zero_signal_thresholds})}.")
    thin_symbols = [
        symbol
        for symbol, data in matrix_by_symbol.items()
        if any("thin_depth" in key or "wide_spread" in key for key in data.get("rejects", {}))
    ]
    if thin_symbols:
        recommendations.append(f"Replace or rotate markets when quality rejects dominate: {sorted(thin_symbols)}.")
    recommendations.append("Run diagnostic arena only after repeated forward-paper windows.")
    return recommendations
