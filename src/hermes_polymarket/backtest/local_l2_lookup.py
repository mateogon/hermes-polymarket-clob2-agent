"""Local L2 orderbook reconstruction from recorded snapshots and deltas."""

from __future__ import annotations

import json

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.state.orderbook_state import OrderBookState
from hermes_polymarket.storage.db import Database


def reconstruct_book_at(
    db: Database,
    *,
    token_id: str,
    target_ts_ms: int,
) -> OrderBookState | None:
    snapshot = db.conn.execute(
        """
        SELECT * FROM l2_book_snapshots
        WHERE token_id = ? AND received_ts_ms <= ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id, target_ts_ms),
    ).fetchone()

    if snapshot is None:
        return None

    state = OrderBookState()
    state.apply(
        DataEvent(
            source="local_l2",
            event_type=EventType.POLY_BOOK,
            event_ts_ms=snapshot["event_ts_ms"],
            received_ts_ms=snapshot["received_ts_ms"],
            key=token_id,
            payload={
                "asset_id": token_id,
                "bids": json.loads(snapshot["bids_json"]),
                "asks": json.loads(snapshot["asks_json"]),
            },
        )
    )

    deltas = db.conn.execute(
        """
        SELECT * FROM l2_price_changes
        WHERE token_id = ? AND received_ts_ms > ? AND received_ts_ms <= ?
        ORDER BY received_ts_ms ASC, id ASC
        """,
        (token_id, snapshot["received_ts_ms"], target_ts_ms),
    )

    for row in deltas:
        state.apply(
            DataEvent(
                source="local_l2",
                event_type=EventType.POLY_PRICE_CHANGE,
                event_ts_ms=row["event_ts_ms"],
                received_ts_ms=row["received_ts_ms"],
                key=token_id,
                payload={
                    "asset_id": token_id,
                    "market": row["market"],
                    "side": row["side"],
                    "price": row["price"],
                    "size": 0.0 if row["removed"] else row["size"],
                    "removed": bool(row["removed"]),
                },
            )
        )

    return state


def nearest_bbo_before(
    db: Database,
    *,
    token_id: str,
    target_ts_ms: int,
) -> dict | None:
    row = db.conn.execute(
        """
        SELECT * FROM l2_bbo_updates
        WHERE token_id = ? AND received_ts_ms <= ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id, target_ts_ms),
    ).fetchone()
    return dict(row) if row else None
