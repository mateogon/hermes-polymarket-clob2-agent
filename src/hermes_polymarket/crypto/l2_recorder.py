"""Bounded local L2 recorder for Polymarket market WebSocket events."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import time
from uuid import uuid4

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.l2 import persist_l2_event


@dataclass(frozen=True)
class L2RecorderSummary:
    run_id: str
    seconds: int
    events_seen: int
    snapshots_seen: int
    deltas_seen: int
    bbo_seen: int
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


def insert_l2_run_start(db: Database, *, run_id: str, token_ids: tuple[str, ...], seconds: int) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO l2_recorder_runs
          (run_id, token_ids_json, seconds, started_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, json.dumps(list(token_ids)), seconds, datetime.now(timezone.utc).isoformat(), "running"),
    )
    db.conn.commit()


def update_l2_run_done(db: Database, summary: L2RecorderSummary) -> None:
    db.conn.execute(
        """
        UPDATE l2_recorder_runs
        SET events_seen = ?,
            snapshots_seen = ?,
            deltas_seen = ?,
            bbo_seen = ?,
            ended_at = ?,
            status = ?
        WHERE run_id = ?
        """,
        (
            summary.events_seen,
            summary.snapshots_seen,
            summary.deltas_seen,
            summary.bbo_seen,
            datetime.now(timezone.utc).isoformat(),
            summary.status,
            summary.run_id,
        ),
    )
    db.conn.commit()


async def run_l2_recorder(
    *,
    db: Database,
    bus: EventBus,
    token_ids: tuple[str, ...],
    seconds: int,
    run_id: str | None = None,
) -> L2RecorderSummary:
    run_id = run_id or f"l2_{uuid4().hex[:12]}"
    insert_l2_run_start(db, run_id=run_id, token_ids=token_ids, seconds=seconds)

    start = time()
    seen = 0
    snapshots = 0
    deltas = 0
    bbo = 0
    token_set = set(token_ids)

    while time() - start < seconds:
        try:
            event = await asyncio.wait_for(bus.next_event(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if event.key not in token_set:
            continue

        if event.event_type in {EventType.POLY_BOOK, EventType.POLY_PRICE_CHANGE, EventType.POLY_BEST_BID_ASK}:
            persist_l2_event(db, event)
            seen += 1
            snapshots += int(event.event_type == EventType.POLY_BOOK)
            deltas += int(event.event_type == EventType.POLY_PRICE_CHANGE)
            bbo += int(event.event_type == EventType.POLY_BEST_BID_ASK)

    summary = L2RecorderSummary(
        run_id=run_id,
        seconds=seconds,
        events_seen=seen,
        snapshots_seen=snapshots,
        deltas_seen=deltas,
        bbo_seen=bbo,
        status="completed",
    )
    update_l2_run_done(db, summary)
    return summary
