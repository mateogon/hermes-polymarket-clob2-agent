"""L2 preflight checks for watchlist tokens."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass
from typing import Any

from hermes_polymarket.config import Settings
from hermes_polymarket.crypto.l2_recorder import run_l2_recorder
from hermes_polymarket.crypto.market_quality import evaluate_market_quality
from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.data_sources.polymarket_market_ws import run_polymarket_market_ws
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.types import OrderBook
from hermes_polymarket.state.orderbook_state import OrderBookState
from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.l2 import persist_l2_event


@dataclass(frozen=True)
class TokenL2Preflight:
    token_id: str
    outcome: str
    rest_book_found: bool
    rest_best_bid: float | None
    rest_best_ask: float | None
    ws_events_seen: int
    ws_book_seen: bool
    ws_bbo_seen: bool
    local_reconstruct_ok: bool
    quality_allowed: bool
    quality_reason: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _book_event(book: OrderBook, *, received_ts_ms: int | None = None, source: str = "clob_rest") -> DataEvent:
    ts = received_ts_ms or now_ms()
    return DataEvent(
        source=source,
        event_type=EventType.POLY_BOOK,
        event_ts_ms=ts,
        received_ts_ms=ts,
        key=book.token_id,
        payload={
            "asset_id": book.token_id,
            "bids": [{"price": str(level.price), "size": str(level.size)} for level in book.bids],
            "asks": [{"price": str(level.price), "size": str(level.size)} for level in book.asks],
            "timestamp": ts,
            "source": source,
        },
    )


def seed_rest_orderbooks(
    *,
    db: Database,
    settings: Settings,
    token_ids: tuple[str, ...],
    book_state: OrderBookState | None = None,
) -> dict[str, dict[str, Any]]:
    client = ClobV2Client(settings)
    seeded: dict[str, dict[str, Any]] = {}
    try:
        for token_id in dict.fromkeys(str(token_id) for token_id in token_ids if token_id):
            try:
                book = client.get_orderbook(token_id)
            except Exception as exc:  # noqa: BLE001 - preflight reports per-token failures.
                seeded[token_id] = {"seeded": False, "reason": str(exc)}
                continue
            event = _book_event(book)
            persist_l2_event(db, event)
            if book_state is not None:
                book_state.apply(event)
            quality = evaluate_market_quality(book)
            seeded[token_id] = {
                "seeded": True,
                "best_bid": book.best_bid,
                "best_ask": book.best_ask,
                "quality": quality.to_dict(),
            }
    finally:
        client.close()
    return seeded


def _ws_counts(db: Database, *, token_id: str, since_ms: int) -> tuple[int, bool, bool]:
    snapshots = db.conn.execute(
        "SELECT COUNT(*) AS n FROM l2_book_snapshots WHERE token_id = ? AND received_ts_ms >= ?",
        (token_id, since_ms),
    ).fetchone()["n"]
    deltas = db.conn.execute(
        "SELECT COUNT(*) AS n FROM l2_price_changes WHERE token_id = ? AND received_ts_ms >= ?",
        (token_id, since_ms),
    ).fetchone()["n"]
    bbo = db.conn.execute(
        "SELECT COUNT(*) AS n FROM l2_bbo_updates WHERE token_id = ? AND received_ts_ms >= ?",
        (token_id, since_ms),
    ).fetchone()["n"]
    return int(snapshots) + int(deltas) + int(bbo), bool(snapshots), bool(bbo)


async def _record_ws(db: Database, *, token_ids: tuple[str, ...], seconds: int) -> None:
    if not token_ids or seconds <= 0:
        return
    bus = EventBus()
    producer = asyncio.create_task(run_polymarket_market_ws(bus, asset_ids=token_ids))
    try:
        await run_l2_recorder(db=db, bus=bus, token_ids=token_ids, seconds=seconds)
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer


async def run_l2_preflight(
    *,
    db: Database,
    settings: Settings,
    symbol: str | None = None,
    condition_id: str | None = None,
    seconds: int = 30,
    require_rest_book: bool = False,
    require_ws_book: bool = False,
    require_bbo: bool = False,
) -> dict[str, Any]:
    rows = crypto_market_watchlist(db, active_only=True, limit=200)
    if symbol:
        rows = [row for row in rows if str(row.get("symbol") or "").lower() == symbol.lower()]
    if condition_id:
        rows = [row for row in rows if str(row.get("condition_id") or "") == condition_id]

    token_rows: list[tuple[dict[str, Any], str, str]] = []
    for market in rows:
        for outcome, token_id in (("YES", market.get("yes_token_id")), ("NO", market.get("no_token_id"))):
            if token_id:
                token_rows.append((market, outcome, str(token_id)))

    client = ClobV2Client(settings)
    rest: dict[str, dict[str, Any]] = {}
    try:
        for _, _, token_id in token_rows:
            if token_id in rest:
                continue
            try:
                book = client.get_orderbook(token_id)
                event = _book_event(book)
                persist_l2_event(db, event)
                quality = evaluate_market_quality(book)
                rest[token_id] = {
                    "found": True,
                    "best_bid": book.best_bid,
                    "best_ask": book.best_ask,
                    "quality": quality.to_dict(),
                }
            except Exception as exc:  # noqa: BLE001
                rest[token_id] = {"found": False, "best_bid": None, "best_ask": None, "quality": {"allowed": False, "reason": str(exc)}}
    finally:
        client.close()

    ws_start_ms = now_ms()
    token_ids = tuple(dict.fromkeys(token_id for _, _, token_id in token_rows))
    if seconds > 0:
        bus = EventBus()
        producer = asyncio.create_task(run_polymarket_market_ws(bus, asset_ids=token_ids))
        try:
            await run_l2_recorder(db=db, bus=bus, token_ids=token_ids, seconds=seconds)
        finally:
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer

    markets: list[dict[str, Any]] = []
    for market in rows:
        token_payloads: list[dict[str, Any]] = []
        for outcome, token_id in (("YES", market.get("yes_token_id")), ("NO", market.get("no_token_id"))):
            if not token_id:
                continue
            token = str(token_id)
            ws_events, ws_book_seen, ws_bbo_seen = _ws_counts(db, token_id=token, since_ms=ws_start_ms)
            rest_row = rest.get(token, {})
            quality = rest_row.get("quality") or {"allowed": False, "reason": "no_rest_book"}
            local_ok = bool(rest_row.get("found")) or ws_book_seen
            usable = local_ok and bool(quality.get("allowed"))
            if require_rest_book and not rest_row.get("found"):
                usable = False
            if require_ws_book and not ws_book_seen:
                usable = False
            if require_bbo and not ws_bbo_seen:
                usable = False
            token_payloads.append(
                TokenL2Preflight(
                    token_id=token,
                    outcome=outcome,
                    rest_book_found=bool(rest_row.get("found")),
                    rest_best_bid=rest_row.get("best_bid"),
                    rest_best_ask=rest_row.get("best_ask"),
                    ws_events_seen=ws_events,
                    ws_book_seen=ws_book_seen,
                    ws_bbo_seen=ws_bbo_seen,
                    local_reconstruct_ok=local_ok,
                    quality_allowed=bool(quality.get("allowed")),
                    quality_reason=str(quality.get("reason") or "unknown"),
                    recommended_action="usable" if usable else "replace_market_or_token",
                ).to_dict()
            )
        markets.append(
            {
                "slug": market["slug"],
                "symbol": market["symbol"],
                "market_type": market.get("market_type", "up_down"),
                "condition_id": market["condition_id"],
                "tokens": token_payloads,
                "recommended_action": "usable" if token_payloads and all(token["recommended_action"] == "usable" for token in token_payloads) else "replace_market_or_token",
            }
        )

    return {
        "mode": "l2_preflight",
        "seconds": seconds,
        "tokens_checked": len(token_rows),
        "markets": markets,
    }
