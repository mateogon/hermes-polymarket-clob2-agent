"""SQLite helpers for local Polymarket L2 recordings."""

from __future__ import annotations

import json

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.storage.db import Database


def insert_l2_book_snapshot(db: Database, event: DataEvent) -> None:
    payload = event.payload
    db.conn.execute(
        """
        INSERT INTO l2_book_snapshots
          (token_id, event_ts_ms, received_ts_ms, bids_json, asks_json, raw_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.key,
            event.event_ts_ms,
            event.received_ts_ms,
            json.dumps(payload.get("bids") or []),
            json.dumps(payload.get("asks") or []),
            json.dumps(payload, sort_keys=True),
        ),
    )
    db.conn.commit()


def insert_l2_price_change(db: Database, event: DataEvent) -> None:
    payload = event.payload
    size = float(payload.get("size") or 0)
    db.conn.execute(
        """
        INSERT INTO l2_price_changes
          (token_id, market, side, price, size, removed, event_ts_ms, received_ts_ms, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.key,
            payload.get("market"),
            str(payload.get("side") or ""),
            float(payload["price"]),
            size,
            int(bool(payload.get("removed")) or size == 0),
            event.event_ts_ms,
            event.received_ts_ms,
            json.dumps(payload, sort_keys=True),
        ),
    )
    db.conn.commit()


def insert_l2_bbo_update(db: Database, event: DataEvent) -> None:
    payload = event.payload
    bid = payload.get("best_bid") or payload.get("bid")
    ask = payload.get("best_ask") or payload.get("ask")
    spread = payload.get("spread")
    bid_f = float(bid) if bid is not None else None
    ask_f = float(ask) if ask is not None else None
    spread_f = float(spread) if spread is not None else (ask_f - bid_f if bid_f is not None and ask_f is not None else None)

    db.conn.execute(
        """
        INSERT INTO l2_bbo_updates
          (token_id, best_bid, best_ask, spread, event_ts_ms, received_ts_ms, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.key,
            bid_f,
            ask_f,
            spread_f,
            event.event_ts_ms,
            event.received_ts_ms,
            json.dumps(payload, sort_keys=True),
        ),
    )
    db.conn.commit()


def persist_l2_event(db: Database, event: DataEvent) -> None:
    if event.event_type == EventType.POLY_BOOK:
        insert_l2_book_snapshot(db, event)
    elif event.event_type == EventType.POLY_PRICE_CHANGE:
        insert_l2_price_change(db, event)
    elif event.event_type == EventType.POLY_BEST_BID_ASK:
        insert_l2_bbo_update(db, event)
