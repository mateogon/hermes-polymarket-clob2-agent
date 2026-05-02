"""SQLite helpers for public wallet positions."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.data_sources.polymarket_positions_api import ClosedPosition, CurrentPosition
from hermes_polymarket.storage.db import Database


def upsert_current_position(db: Database, pos: CurrentPosition) -> None:
    db.conn.execute(
        """
        INSERT INTO wallet_current_positions
          (wallet, condition_id, asset_id, outcome, size, avg_price, initial_value,
           current_value, cash_pnl, percent_pnl, total_bought, realized_pnl, cur_price,
           redeemable, mergeable, negative_risk, opposite_asset, opposite_outcome,
           slug, title, event_slug, end_date, raw_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(wallet, condition_id, asset_id) DO UPDATE SET
          outcome = excluded.outcome,
          size = excluded.size,
          avg_price = excluded.avg_price,
          initial_value = excluded.initial_value,
          current_value = excluded.current_value,
          cash_pnl = excluded.cash_pnl,
          percent_pnl = excluded.percent_pnl,
          total_bought = excluded.total_bought,
          realized_pnl = excluded.realized_pnl,
          cur_price = excluded.cur_price,
          redeemable = excluded.redeemable,
          mergeable = excluded.mergeable,
          negative_risk = excluded.negative_risk,
          opposite_asset = excluded.opposite_asset,
          opposite_outcome = excluded.opposite_outcome,
          slug = excluded.slug,
          title = excluded.title,
          event_slug = excluded.event_slug,
          end_date = excluded.end_date,
          raw_json = excluded.raw_json,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            pos.wallet,
            pos.condition_id,
            pos.asset_id,
            pos.outcome,
            pos.size,
            pos.avg_price,
            pos.initial_value,
            pos.current_value,
            pos.cash_pnl,
            pos.percent_pnl,
            pos.total_bought,
            pos.realized_pnl,
            pos.cur_price,
            int(pos.redeemable),
            int(pos.mergeable),
            int(pos.negative_risk),
            pos.opposite_asset,
            pos.opposite_outcome,
            pos.slug,
            pos.title,
            pos.event_slug,
            pos.end_date,
            json.dumps(pos.raw, sort_keys=True),
        ),
    )
    db.conn.commit()


def upsert_current_positions(db: Database, positions: list[CurrentPosition]) -> int:
    for pos in positions:
        upsert_current_position(db, pos)
    return len(positions)


def insert_closed_position(db: Database, pos: ClosedPosition) -> bool:
    cur = db.conn.execute(
        """
        INSERT OR IGNORE INTO wallet_closed_positions
          (wallet, condition_id, asset_id, outcome, avg_price, total_bought,
           realized_pnl, cur_price, timestamp, opposite_asset, opposite_outcome,
           slug, title, event_slug, end_date, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pos.wallet,
            pos.condition_id,
            pos.asset_id,
            pos.outcome,
            pos.avg_price,
            pos.total_bought,
            pos.realized_pnl,
            pos.cur_price,
            pos.timestamp,
            pos.opposite_asset,
            pos.opposite_outcome,
            pos.slug,
            pos.title,
            pos.event_slug,
            pos.end_date,
            json.dumps(pos.raw, sort_keys=True),
        ),
    )
    db.conn.commit()
    return cur.rowcount > 0


def insert_closed_positions(db: Database, positions: list[ClosedPosition]) -> dict[str, int]:
    inserted = 0
    for pos in positions:
        inserted += int(insert_closed_position(db, pos))
    return {"fetched": len(positions), "inserted": inserted, "duplicates": len(positions) - inserted}


def current_positions(db: Database, wallet: str) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT * FROM wallet_current_positions WHERE LOWER(wallet)=LOWER(?) ORDER BY current_value DESC",
        (wallet,),
    )
    return [dict(row) for row in rows]


def closed_positions(db: Database, wallet: str, limit: int = 1000) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        """
        SELECT * FROM wallet_closed_positions
        WHERE LOWER(wallet)=LOWER(?)
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (wallet, limit),
    )
    return [dict(row) for row in rows]
