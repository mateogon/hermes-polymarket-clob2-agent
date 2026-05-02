"""Storage helpers for crypto market watchlists."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.storage.db import Database


def upsert_crypto_market_watchlist(db: Database, row: dict[str, Any]) -> None:
    db.conn.execute(
        """
        INSERT INTO crypto_market_watchlist
          (condition_id, slug, question, symbol, yes_token_id, no_token_id,
           active, discovered_at_ms, end_ts_ms, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(condition_id, yes_token_id, no_token_id) DO UPDATE SET
          slug = excluded.slug,
          question = excluded.question,
          symbol = excluded.symbol,
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


def watchlist_token_ids(db: Database, *, active_only: bool = True, limit: int = 100) -> tuple[str, ...]:
    token_ids: list[str] = []
    for row in crypto_market_watchlist(db, active_only=active_only, limit=limit):
        token_ids.extend([str(row["yes_token_id"]), str(row["no_token_id"])])
    return tuple(dict.fromkeys(token_id for token_id in token_ids if token_id))
