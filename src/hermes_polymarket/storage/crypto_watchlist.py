"""Storage helpers for crypto market watchlists."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.storage.db import Database


def upsert_crypto_market_watchlist(db: Database, row: dict[str, Any]) -> None:
    direction_map = dict(row.get("direction_map", {}))
    up_token_id = row.get("up_token_id") or direction_map.get("up")
    down_token_id = row.get("down_token_id") or direction_map.get("down")
    db.conn.execute(
        """
        INSERT INTO crypto_market_watchlist
          (condition_id, slug, question, symbol, yes_token_id, no_token_id,
           up_token_id, down_token_id, market_type, strike_price, comparator, resolution_ts,
           direction_map_json, active, discovered_at_ms, end_ts_ms, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(condition_id, yes_token_id, no_token_id) DO UPDATE SET
          slug = excluded.slug,
          question = excluded.question,
          symbol = excluded.symbol,
          up_token_id = excluded.up_token_id,
          down_token_id = excluded.down_token_id,
          market_type = excluded.market_type,
          strike_price = excluded.strike_price,
          comparator = excluded.comparator,
          resolution_ts = excluded.resolution_ts,
          direction_map_json = excluded.direction_map_json,
          active = excluded.active,
          end_ts_ms = excluded.end_ts_ms,
          raw_json = excluded.raw_json
        """,
        (
            row["condition_id"],
            row["slug"],
            row.get("question"),
            row["symbol"],
            row["yes_token_id"],
            row["no_token_id"],
            up_token_id,
            down_token_id,
            row.get("market_type", "up_down"),
            row.get("strike_price"),
            row.get("comparator"),
            row.get("resolution_ts"),
            json.dumps(direction_map, sort_keys=True),
            int(row.get("active", True)),
            int(row["discovered_at_ms"]),
            row.get("end_ts_ms"),
            json.dumps(row.get("raw", {}), sort_keys=True),
        ),
    )
    db.conn.commit()


def crypto_market_watchlist(db: Database, *, active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
    where = "WHERE active = 1" if active_only else ""
    rows = db.conn.execute(
        f"""
        SELECT * FROM crypto_market_watchlist
        {where}
        ORDER BY discovered_at_ms DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in rows]


def clear_crypto_market_watchlist(db: Database) -> int:
    cur = db.conn.execute("DELETE FROM crypto_market_watchlist")
    db.conn.commit()
    return int(cur.rowcount)


def set_crypto_market_watchlist_active(db: Database, *, condition_id: str, active: bool) -> int:
    cur = db.conn.execute(
        "UPDATE crypto_market_watchlist SET active = ? WHERE condition_id = ?",
        (int(active), condition_id),
    )
    db.conn.commit()
    return int(cur.rowcount)


def set_crypto_market_reference(
    db: Database,
    *,
    condition_id: str,
    reference_price: float,
    window_start_ts: int | None = None,
    window_end_ts: int | None = None,
) -> int:
    rows = db.conn.execute("SELECT id, raw_json FROM crypto_market_watchlist WHERE condition_id = ?", (condition_id,)).fetchall()
    updated = 0
    for row in rows:
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        raw["reference_price"] = reference_price
        if window_start_ts is not None:
            raw["window_start_ts"] = window_start_ts
        if window_end_ts is not None:
            raw["window_end_ts"] = window_end_ts
        db.conn.execute("UPDATE crypto_market_watchlist SET raw_json = ? WHERE id = ?", (json.dumps(raw, sort_keys=True), row["id"]))
        updated += 1
    db.conn.commit()
    return updated


def watchlist_reference(row: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except json.JSONDecodeError:
        raw = {}
    return {
        "reference_price": raw.get("reference_price"),
        "window_start_ts": raw.get("window_start_ts"),
        "window_end_ts": raw.get("window_end_ts") or row.get("end_ts_ms"),
    }


def watchlist_token_ids(db: Database, *, active_only: bool = True, limit: int = 100) -> tuple[str, ...]:
    token_ids: list[str] = []
    for row in crypto_market_watchlist(db, active_only=active_only, limit=limit):
        token_ids.extend([str(row["yes_token_id"]), str(row["no_token_id"])])
    return tuple(dict.fromkeys(token_id for token_id in token_ids if token_id))
