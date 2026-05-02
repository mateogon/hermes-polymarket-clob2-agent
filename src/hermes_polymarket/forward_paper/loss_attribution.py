"""Loss attribution for forward-paper campaign evidence."""

from __future__ import annotations

import glob
import json
import sqlite3
from collections import defaultdict
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
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _threshold(run: dict[str, Any] | None) -> str:
    if not run:
        return "unknown"
    config = _loads(run.get("config_json"), {})
    value = config.get("min_move_pct")
    return str(value) if value is not None else "unknown"


def _bucket_spread(spread: float | None) -> str:
    if spread is None:
        return "unknown"
    cents = spread * 100.0
    if cents <= 1:
        return "<=1c"
    if cents <= 2:
        return "1-2c"
    if cents <= 4:
        return "2-4c"
    return ">4c"


def _bucket_slippage(slippage: float | None) -> str:
    if slippage is None:
        return "unknown"
    cents = slippage * 100.0
    if cents <= 0.5:
        return "<=0.5c"
    if cents <= 1:
        return "0.5-1c"
    if cents <= 2:
        return "1-2c"
    return ">2c"


def _bucket_time(ms: int | None) -> str:
    if ms is None:
        return "unknown"
    seconds = ms / 1000.0
    if seconds <= 60:
        return "<=60s"
    if seconds <= 300:
        return "60-300s"
    if seconds <= 900:
        return "300-900s"
    return ">900s"


def _add(bucket: dict[str, Any], pnl: float) -> None:
    bucket["positions"] += 1
    bucket["net_pnl"] += pnl


def _empty_bucket() -> dict[str, Any]:
    return {"positions": 0, "net_pnl": 0.0}


def load_closed_positions(db_paths: list[str | Path], *, include_fixture: bool = False) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for raw_path in db_paths:
        db_path = str(raw_path)
        if not Path(db_path).exists():
            continue
        conn = _connect(db_path)
        try:
            if not all(_has_table(conn, table) for table in ("forward_paper_runs", "forward_paper_signals", "forward_paper_positions")):
                continue
            run_rows = {row["run_id"]: dict(row) for row in conn.execute("SELECT * FROM forward_paper_runs")}
            signal_rows = {
                (row["signal_id"], row["token_id"]): dict(row)
                for row in conn.execute("SELECT * FROM forward_paper_signals")
            }
            where = "status='closed'" if include_fixture else "status='closed' AND fixture=0"
            for row in conn.execute(f"SELECT * FROM forward_paper_positions WHERE {where}"):
                data = dict(row)
                signal = signal_rows.get((data.get("signal_id"), data.get("token_id"))) or {}
                run = run_rows.get(data.get("run_id"))
                payload = _loads(signal.get("payload_json"), {})
                time_in_position = (
                    int(data["exit_ts_ms"]) - int(data["entry_ts_ms"])
                    if data.get("exit_ts_ms") is not None and data.get("entry_ts_ms") is not None
                    else None
                )
                data.update(
                    {
                        "db": db_path,
                        "threshold": _threshold(run),
                        "external_move_pct": signal.get("external_move_pct"),
                        "entry_slippage": payload.get("slippage"),
                        "market_quality_reason": (payload.get("market_quality") or {}).get("reason") if isinstance(payload.get("market_quality"), dict) else None,
                        "source_consensus_sources": (payload.get("source_consensus") or {}).get("sources") if isinstance(payload.get("source_consensus"), dict) else None,
                        "time_in_position_ms": time_in_position,
                    }
                )
                positions.append(data)
        finally:
            conn.close()
    return positions


def loss_attribution(db_paths: list[str | Path], *, include_fixture: bool = False) -> dict[str, Any]:
    positions = load_closed_positions(db_paths, include_fixture=include_fixture)
    by_threshold: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_symbol: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_exit_reason: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_spread: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_slippage: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_time: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_run: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)

    for pos in positions:
        pnl = float(pos.get("net_pnl") or 0.0)
        _add(by_threshold[str(pos.get("threshold") or "unknown")], pnl)
        _add(by_symbol[str(pos.get("symbol") or "unknown")], pnl)
        _add(by_exit_reason[str(pos.get("exit_reason") or "unknown")], pnl)
        _add(by_spread[_bucket_spread(pos.get("spread_at_entry"))], pnl)
        _add(by_slippage[_bucket_slippage(pos.get("entry_slippage"))], pnl)
        _add(by_time[_bucket_time(pos.get("time_in_position_ms"))], pnl)
        _add(by_run[str(pos.get("run_id") or "unknown")], pnl)

    net_pnl = sum(float(pos.get("net_pnl") or 0.0) for pos in positions)
    worst = sorted(positions, key=lambda row: float(row.get("net_pnl") or 0.0))[:10]
    best = sorted(positions, key=lambda row: float(row.get("net_pnl") or 0.0), reverse=True)[:10]
    hypotheses: list[str] = []
    if net_pnl < 0:
        hypotheses.append("threshold_only_signal_too_noisy")
    if any("thin_depth" in str(pos.get("market_quality_reason") or "") for pos in positions):
        hypotheses.append("market_quality_too_thin")
    if any(float(pos.get("spread_at_entry") or 0.0) * 100.0 > 2.0 for pos in positions):
        hypotheses.append("entry_spread_too_wide")
    if positions:
        hypotheses.append("entries_not_confirmed_by_stale_bbo")
        hypotheses.append("exit_model_may_be_too_aggressive_or_misaligned")

    return {
        "mode": "forward_paper_loss_attribution",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "positions": len(positions),
        "net_pnl": net_pnl,
        "by_threshold": dict(by_threshold),
        "by_symbol": dict(by_symbol),
        "by_exit_reason": dict(by_exit_reason),
        "by_spread_bucket": dict(by_spread),
        "by_slippage_bucket": dict(by_slippage),
        "by_time_in_position_bucket": dict(by_time),
        "pnl_by_run": dict(by_run),
        "worst_positions": [_compact_position(row) for row in worst],
        "best_positions": [_compact_position(row) for row in best],
        "dominant_loss_hypotheses": hypotheses,
        "recommendation": "Do not continue current strategy unchanged." if net_pnl < 0 else "Evidence is not negative, but still requires review.",
    }


def _compact_position(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "position_id",
        "run_id",
        "symbol",
        "threshold",
        "entry_price",
        "exit_price",
        "net_pnl",
        "exit_reason",
        "spread_at_entry",
        "entry_slippage",
        "time_in_position_ms",
        "external_move_pct",
    )
    return {key: row.get(key) for key in keys}


def write_loss_attribution(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path
