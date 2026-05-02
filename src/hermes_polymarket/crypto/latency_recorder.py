"""Bounded crypto latency recorder over normalized public data events."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from time import time

from hermes_polymarket.crypto.event_adapter import bbo_from_event, price_reading_from_event
from hermes_polymarket.crypto.runtime_state import CryptoRuntimeState
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.signals.crypto_latency_detector import detect_external_move
from hermes_polymarket.signals.source_consensus import consensus_price
from hermes_polymarket.storage.crypto_latency import insert_crypto_consensus_tick, insert_crypto_latency_event
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class RecorderConfig:
    symbols: tuple[str, ...]
    seconds: int
    min_sources: int = 2
    max_age_ms: int = 2500
    max_deviation_pct: float = 0.25
    min_move_pct: float = 0.08
    cooldown_ms: int = 5000
    max_events: int = 500


@dataclass(frozen=True)
class RecorderSummary:
    seconds: int
    events_seen: int
    consensus_ticks: int
    latency_events: int
    dropped_events: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def run_crypto_latency_recorder(
    *,
    db: Database,
    bus: EventBus,
    config: RecorderConfig,
    state: CryptoRuntimeState | None = None,
) -> RecorderSummary:
    state = state or CryptoRuntimeState()
    start = time()
    seen = 0
    consensus_count = 0
    latency_count = 0
    symbols = {symbol.lower() for symbol in config.symbols}

    while time() - start < config.seconds:
        try:
            event = await asyncio.wait_for(bus.next_event(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        seen += 1
        db.insert_data_event(event)
        db.upsert_source_health(event, dropped_events=bus.dropped_events)

        reading = price_reading_from_event(event)
        if reading is not None and reading.symbol in symbols:
            state.update_reading(reading)
            current = consensus_price(
                state.readings(reading.symbol),
                now_ms=event.received_ts_ms,
                max_age_ms=config.max_age_ms,
                max_deviation_pct_allowed=config.max_deviation_pct,
                min_sources=config.min_sources,
            )
            if current is not None:
                insert_crypto_consensus_tick(
                    db,
                    symbol=current.symbol,
                    consensus_price=current.price,
                    sources=current.sources,
                    max_deviation_pct=current.max_deviation_pct,
                    received_ts_ms=event.received_ts_ms,
                )
                consensus_count += 1

                previous = state.last_consensus_by_symbol.get(current.symbol)
                state.last_consensus_by_symbol[current.symbol] = current

                if previous is not None:
                    last_event_ts = state.last_event_ts_by_symbol.get(current.symbol, 0)
                    if event.received_ts_ms - last_event_ts >= config.cooldown_ms:
                        latency_event = detect_external_move(
                            symbol=current.symbol,
                            previous=previous,
                            current=current,
                            min_move_pct=config.min_move_pct,
                            detected_ts_ms=event.received_ts_ms,
                        )
                        if latency_event is not None:
                            state.last_event_ts_by_symbol[current.symbol] = event.received_ts_ms
                            insert_crypto_latency_event(
                                db,
                                {
                                    "event_id": latency_event.event_id,
                                    "symbol": latency_event.symbol,
                                    "external_move_pct": latency_event.external_move_pct,
                                    "external_move_detected_ts_ms": latency_event.detected_ts_ms,
                                    "payload": {
                                        "data_quality": "paper_live",
                                        "reference_price": latency_event.reference_price,
                                        "current_price": latency_event.current_price,
                                        "sources": current.sources,
                                    },
                                },
                            )
                            latency_count += 1
                            if latency_count >= config.max_events:
                                break

        bbo = bbo_from_event(event)
        if bbo is not None:
            token_id, payload = bbo
            state.update_bbo(token_id, payload)

    return RecorderSummary(
        seconds=config.seconds,
        events_seen=seen,
        consensus_ticks=consensus_count,
        latency_events=latency_count,
        dropped_events=bus.dropped_events,
    )
