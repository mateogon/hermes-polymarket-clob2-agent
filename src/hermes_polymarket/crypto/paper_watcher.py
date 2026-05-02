"""Forward paper watcher for crypto latency signals.

This module observes public crypto feeds and Polymarket market websocket data in
the same wall-clock window. It records paper-only opportunities; it never posts
orders.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from time import time
from typing import Any
from uuid import uuid4

from hermes_polymarket.crypto.event_adapter import price_reading_from_event
from hermes_polymarket.crypto.runtime_state import CryptoRuntimeState
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.signals.crypto_latency_detector import detect_external_move
from hermes_polymarket.signals.source_consensus import consensus_price
from hermes_polymarket.state.orderbook_state import OrderBookState
from hermes_polymarket.storage.crypto_latency import (
    insert_crypto_consensus_tick,
    insert_crypto_latency_event,
    insert_crypto_latency_opportunity,
)
from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.l2 import persist_l2_event


@dataclass(frozen=True)
class PaperWatcherConfig:
    symbols: tuple[str, ...]
    seconds: int
    amount_usd: float = 5.0
    min_sources: int = 2
    max_age_ms: int = 2500
    max_deviation_pct: float = 0.25
    min_move_pct: float = 0.03
    cooldown_ms: int = 5000
    max_events: int = 500


@dataclass(frozen=True)
class PaperWatcherSummary:
    seconds: int
    events_seen: int
    consensus_ticks: int
    signals_generated: int
    latency_events: int
    paper_opportunities: int
    fills_simulated: int
    risk_rejected: int
    l2_events_seen: int
    dropped_events: int
    watchlist_markets: int
    watchlist_token_count: int
    source_health: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def token_market_map(watchlist: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for market in watchlist:
        yes_token = str(market["yes_token_id"])
        no_token = str(market["no_token_id"])
        mapping[yes_token] = {**market, "token_id": yes_token, "outcome": "YES"}
        mapping[no_token] = {**market, "token_id": no_token, "outcome": "NO"}
    return mapping


def _tokens_for_symbol(token_map: dict[str, dict[str, Any]], symbol: str) -> list[tuple[str, dict[str, Any]]]:
    return [(token_id, market) for token_id, market in token_map.items() if str(market.get("symbol", "")).lower() == symbol]


def _persist_signal_event(
    db: Database,
    *,
    event_id: str,
    symbol: str,
    market: dict[str, Any] | None,
    external_move_pct: float,
    detected_ts_ms: int,
    reference_price: float,
    current_price: float,
    sources: tuple[str, ...],
) -> None:
    insert_crypto_latency_event(
        db,
        {
            "event_id": event_id,
            "symbol": symbol,
            "condition_id": market.get("condition_id") if market else None,
            "external_move_pct": external_move_pct,
            "external_move_detected_ts_ms": detected_ts_ms,
            "payload": {
                "data_quality": "paper_live",
                "mode": "forward_paper_watcher",
                "reference_price": reference_price,
                "current_price": current_price,
                "sources": sources,
                "slug": market.get("slug") if market else None,
            },
        },
    )


def _record_token_opportunity(
    db: Database,
    *,
    event_id: str,
    token_id: str,
    market: dict[str, Any],
    book_state: OrderBookState,
    amount_usd: float,
) -> tuple[int, int, int]:
    state = book_state.by_token.get(token_id)
    fill = None
    if state is not None:
        fill = simulate_buy_fill(state.as_orderbook(), amount_usd, order_type="fok")

    filled = bool(fill and fill.filled)
    row = {
        "opportunity_id": f"paper_opp_{uuid4().hex[:12]}",
        "event_id": event_id,
        "token_id": token_id,
        "outcome": str(market.get("outcome") or ""),
        "side": "BUY",
        "amount_usd": amount_usd,
        "avg_price": fill.avg_price if fill else None,
        "shares": fill.total_shares if fill else None,
        "fill_status": fill.status if fill else "no_local_book_state",
        "risk_allowed": False,
        "risk_reason": "paper_forward_observation_only" if filled else "no_executable_fill",
        "data_quality": "paper_live",
        "payload": {
            "mode": "forward_paper_watcher",
            "condition_id": market.get("condition_id"),
            "slug": market.get("slug"),
            "symbol": market.get("symbol"),
            "best_bid": state.best_bid if state else None,
            "best_ask": state.best_ask if state else None,
            "spread": state.spread if state else None,
        },
    }
    insert_crypto_latency_opportunity(db, row)
    return 1, int(filled), 1


async def run_crypto_paper_watcher(
    *,
    db: Database,
    bus: EventBus,
    config: PaperWatcherConfig,
    watchlist: list[dict[str, Any]] | None = None,
    runtime_state: CryptoRuntimeState | None = None,
    book_state: OrderBookState | None = None,
) -> PaperWatcherSummary:
    runtime_state = runtime_state or CryptoRuntimeState()
    book_state = book_state or OrderBookState()
    watchlist = watchlist if watchlist is not None else crypto_market_watchlist(db, active_only=True, limit=100)
    token_map = token_market_map(watchlist)
    runtime_state.token_to_market.update(token_map)

    started = time()
    events_seen = 0
    consensus_ticks = 0
    signals_generated = 0
    latency_events = 0
    opportunities = 0
    fills = 0
    risk_rejected = 0
    l2_events = 0

    while time() - started < config.seconds:
        try:
            event = await asyncio.wait_for(bus.next_event(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        events_seen += 1
        db.insert_data_event(event)
        db.upsert_source_health(event, dropped_events=bus.dropped_events)

        if event.event_type in {EventType.POLY_BOOK, EventType.POLY_PRICE_CHANGE, EventType.POLY_BEST_BID_ASK, EventType.POLY_MARKET_RESOLVED}:
            book_state.apply(event)
            if event.event_type in {EventType.POLY_BOOK, EventType.POLY_PRICE_CHANGE, EventType.POLY_BEST_BID_ASK}:
                persist_l2_event(db, event)
                l2_events += 1

        reading = price_reading_from_event(event)
        if reading is None or reading.symbol not in config.symbols:
            continue

        runtime_state.update_reading(reading)
        current = consensus_price(
            runtime_state.readings(reading.symbol),
            now_ms=event.received_ts_ms,
            max_age_ms=config.max_age_ms,
            max_deviation_pct_allowed=config.max_deviation_pct,
            min_sources=config.min_sources,
        )
        if current is None:
            continue

        insert_crypto_consensus_tick(
            db,
            symbol=current.symbol,
            consensus_price=current.price,
            sources=current.sources,
            max_deviation_pct=current.max_deviation_pct,
            received_ts_ms=event.received_ts_ms,
        )
        consensus_ticks += 1

        previous = runtime_state.last_consensus_by_symbol.get(current.symbol)
        runtime_state.last_consensus_by_symbol[current.symbol] = current
        if previous is None:
            continue

        last_event_ts = runtime_state.last_event_ts_by_symbol.get(current.symbol, 0)
        if event.received_ts_ms - last_event_ts < config.cooldown_ms:
            continue

        signal = detect_external_move(
            symbol=current.symbol,
            previous=previous,
            current=current,
            min_move_pct=config.min_move_pct,
            detected_ts_ms=event.received_ts_ms,
        )
        if signal is None:
            continue

        runtime_state.last_event_ts_by_symbol[current.symbol] = event.received_ts_ms
        signals_generated += 1
        latency_events += 1
        matched = _tokens_for_symbol(token_map, current.symbol)
        first_market = matched[0][1] if matched else None
        _persist_signal_event(
            db,
            event_id=signal.event_id,
            symbol=signal.symbol,
            market=first_market,
            external_move_pct=signal.external_move_pct,
            detected_ts_ms=signal.detected_ts_ms,
            reference_price=signal.reference_price,
            current_price=signal.current_price,
            sources=current.sources,
        )

        for token_id, market in matched:
            opp_delta, fill_delta, reject_delta = _record_token_opportunity(
                db,
                event_id=signal.event_id,
                token_id=token_id,
                market=market,
                book_state=book_state,
                amount_usd=config.amount_usd,
            )
            opportunities += opp_delta
            fills += fill_delta
            risk_rejected += reject_delta

        if latency_events >= config.max_events:
            break

    return PaperWatcherSummary(
        seconds=config.seconds,
        events_seen=events_seen,
        consensus_ticks=consensus_ticks,
        signals_generated=signals_generated,
        latency_events=latency_events,
        paper_opportunities=opportunities,
        fills_simulated=fills,
        risk_rejected=risk_rejected,
        l2_events_seen=l2_events,
        dropped_events=bus.dropped_events,
        watchlist_markets=len(watchlist),
        watchlist_token_count=len(token_map),
        source_health=[dict(row) for row in db.source_health()],
    )
