"""Storage helpers for raw public source samples."""

from __future__ import annotations

import json

from hermes_polymarket.data_sources.base import DataEvent
from hermes_polymarket.storage.db import Database


def insert_raw_sample(db: Database, event: DataEvent) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO raw_source_samples
          (source, event_type, event_key, received_ts_ms, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.source,
            event.event_type.value,
            event.key,
            event.received_ts_ms,
            json.dumps(event.payload, sort_keys=True),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def raw_samples(db: Database, *, source: str, limit: int = 20) -> list[dict]:
    rows = db.conn.execute(
        """
        SELECT * FROM raw_source_samples
        WHERE source = ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT ?
        """,
        (source, limit),
    )
    return [dict(row) for row in rows]
