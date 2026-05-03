"""Run-end reconciliation for forward paper positions.

These helpers are paper-only. A run-end mark is not an execution claim; it is a
mark-to-market close used to compare short campaigns with leftover open
positions.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from hermes_polymarket.backtest.local_l2_lookup import reconstruct_book_at
from hermes_polymarket.data_sources.base import now_ms
from hermes_polymarket.forward_paper.lifecycle import ForwardPaperPosition, close_position, mark_position, update_excursions
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import forward_positions, upsert_forward_position


def _position_from_row(row: dict[str, Any]) -> ForwardPaperPosition:
    fields = {field: row[field] for field in ForwardPaperPosition.__dataclass_fields__ if field in row}
    return ForwardPaperPosition(**fields)


def _latest_mark(
    db: Database,
    *,
    token_id: str,
    after_ts_ms: int,
    before_ts_ms: int | None = None,
) -> tuple[int, float] | None:
    before = before_ts_ms if before_ts_ms is not None else now_ms()
    bbo = db.conn.execute(
        """
        SELECT received_ts_ms, best_bid
        FROM l2_bbo_updates
        WHERE token_id = ? AND received_ts_ms >= ? AND received_ts_ms <= ? AND best_bid IS NOT NULL
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id, after_ts_ms, before),
    ).fetchone()
    if bbo is not None:
        return int(bbo["received_ts_ms"]), float(bbo["best_bid"])

    snap = db.conn.execute(
        """
        SELECT received_ts_ms
        FROM l2_book_snapshots
        WHERE token_id = ? AND received_ts_ms >= ? AND received_ts_ms <= ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id, after_ts_ms, before),
    ).fetchone()
    if snap is None:
        return None
    before = before_ts_ms if before_ts_ms is not None else int(snap["received_ts_ms"])
    state = reconstruct_book_at(db, token_id=token_id, target_ts_ms=before)
    if state is None or token_id not in state.by_token:
        return None
    bid = state.by_token[token_id].best_bid
    return (before, float(bid)) if bid is not None else None


def reconcile_open_positions(
    db: Database,
    *,
    run_id: str,
    policy: str = "mark_to_last_bid",
    before_ts_ms: int | None = None,
) -> dict[str, Any]:
    if policy not in {"mark_to_last_bid", "keep_open"}:
        raise ValueError("policy must be mark_to_last_bid or keep_open")

    open_rows = forward_positions(db, run_id=run_id, status="open", include_fixture=True, limit=10_000)
    if policy == "keep_open":
        return {
            "mode": "forward_paper_only",
            "run_id": run_id,
            "policy": policy,
            "closed": 0,
            "kept_open": len(open_rows),
            "warnings": [],
            "positions": [],
        }

    closed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    warnings: list[str] = []

    for row in open_rows:
        mark = _latest_mark(db, token_id=str(row["token_id"]), after_ts_ms=int(row["entry_ts_ms"]), before_ts_ms=before_ts_ms)
        if mark is None:
            kept.append({"position_id": row["position_id"], "token_id": row["token_id"], "reason": "no_mark_available"})
            continue
        ts_ms, mark_price = mark
        pos = _position_from_row(row)
        _, mfe, mae = mark_position(pos, mark_price=mark_price)
        marked = update_excursions(pos, mfe=mfe, mae=mae)
        final = close_position(marked, ts_ms=ts_ms, exit_price=mark_price, reason="run_end_mark")
        final = ForwardPaperPosition(**{**asdict(final), "data_quality": "paper_live_mark_to_market"})
        upsert_forward_position(
            db,
            final,
            payload={"source": "reconcile_open_positions", "policy": policy, "mark_to_market_exit_not_actual_fill": True},
            fixture=bool(row.get("fixture")),
        )
        closed.append(
            {
                "position_id": final.position_id,
                "token_id": final.token_id,
                "exit_ts_ms": final.exit_ts_ms,
                "exit_price": final.exit_price,
                "net_pnl": final.net_pnl,
                "exit_reason": final.exit_reason,
            }
        )

    if kept:
        warnings.append("no_mark_available")
    if closed:
        warnings.insert(0, "mark_to_market_exit_not_actual_fill")

    return {
        "mode": "forward_paper_only",
        "run_id": run_id,
        "policy": policy,
        "closed": len(closed),
        "kept_open": len(kept),
        "warnings": warnings,
        "positions": closed,
        "kept": kept,
    }
