"""Shadow exit replay for stored forward-paper positions."""

from __future__ import annotations

import glob
import json
import sqlite3
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


def load_positions_with_marks(db_paths: list[str | Path], *, include_fixture: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_path in db_paths:
        db_path = str(raw_path)
        if not Path(db_path).exists():
            continue
        conn = _connect(db_path)
        try:
            if not all(_has_table(conn, table) for table in ("forward_paper_positions", "forward_paper_marks")):
                continue
            where = "status='closed'" if include_fixture else "status='closed' AND fixture=0"
            for row in conn.execute(f"SELECT * FROM forward_paper_positions WHERE {where}"):
                pos = dict(row)
                marks = [
                    dict(mark)
                    for mark in conn.execute(
                        "SELECT * FROM forward_paper_marks WHERE position_id=? ORDER BY ts_ms ASC, id ASC",
                        (pos["position_id"],),
                    )
                ]
                out.append({**pos, "db": db_path, "marks": marks})
        finally:
            conn.close()
    return out


def replay_position_exit(position: dict[str, Any], *, take_profit_cents: float, stop_loss_cents: float, timeout_seconds: int) -> dict[str, Any]:
    entry = float(position["entry_price"])
    shares = float(position["shares"])
    entry_ts = int(position["entry_ts_ms"])
    fallback_exit_ts = position.get("exit_ts_ms")
    fallback_exit_price = position.get("exit_price")

    for mark in position.get("marks", []):
        mark_price = mark.get("mark_price")
        if mark_price is None:
            continue
        price = float(mark_price)
        ts = int(mark["ts_ms"])
        reason = None
        if price >= entry + take_profit_cents / 100.0:
            reason = "take_profit"
        elif price <= entry - stop_loss_cents / 100.0:
            reason = "stop_loss"
        elif ts - entry_ts >= timeout_seconds * 1000:
            reason = "timeout"
        if reason:
            pnl = shares * (price - entry)
            return {"exit_ts_ms": ts, "exit_price": price, "exit_reason": reason, "net_pnl": pnl}

    if fallback_exit_ts is not None and fallback_exit_price is not None:
        price = float(fallback_exit_price)
        pnl = shares * (price - entry)
        return {"exit_ts_ms": int(fallback_exit_ts), "exit_price": price, "exit_reason": "actual_exit_fallback", "net_pnl": pnl}
    return {"exit_ts_ms": None, "exit_price": None, "exit_reason": "no_exit", "net_pnl": 0.0}


def shadow_exit_grid(
    db_paths: list[str | Path],
    *,
    take_profit_cents: list[float] | None = None,
    stop_loss_cents: list[float] | None = None,
    timeout_seconds: list[int] | None = None,
    include_fixture: bool = False,
) -> dict[str, Any]:
    positions = load_positions_with_marks(db_paths, include_fixture=include_fixture)
    tps = take_profit_cents or [3, 5, 8, 12]
    sls = stop_loss_cents or [2, 4, 6]
    timeouts = timeout_seconds or [60, 120, 300, 900]
    rows: list[dict[str, Any]] = []
    for tp in tps:
        for sl in sls:
            for timeout in timeouts:
                pnls = [replay_position_exit(pos, take_profit_cents=tp, stop_loss_cents=sl, timeout_seconds=timeout)["net_pnl"] for pos in positions]
                rows.append(
                    {
                        "take_profit_cents": tp,
                        "stop_loss_cents": sl,
                        "timeout_seconds": timeout,
                        "positions": len(positions),
                        "net_pnl": sum(float(value) for value in pnls),
                    }
                )
    best = max(rows, key=lambda row: row["net_pnl"], default=None)
    current_pnl = sum(float(pos.get("net_pnl") or 0.0) for pos in positions)
    conclusion = "No positions to replay."
    if best is not None:
        conclusion = "Even best shadow exit remains negative; entry signal likely bad." if best["net_pnl"] < 0 else "Exit settings may explain part of losses; investigate before changing strategy."
    return {
        "mode": "forward_paper_shadow_exit_replay",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "positions": len(positions),
        "current_config": {"net_pnl": current_pnl},
        "best_config": best,
        "grid": rows,
        "conclusion": conclusion,
    }


def write_shadow_exit_grid(result: dict[str, Any], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return path
