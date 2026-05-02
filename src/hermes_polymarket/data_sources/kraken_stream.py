"""Kraken public ticker normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


KRAKEN_WS = "wss://ws.kraken.com/v2"


def kraken_ticker_subscription(symbols: Iterable[str]) -> dict[str, Any]:
    pairs = [str(symbol) for symbol in symbols if symbol]
    if not pairs:
        raise ValueError("symbols cannot be empty")
    return {"method": "subscribe", "params": {"channel": "ticker", "symbol": pairs}}


def normalize_kraken_message(message: dict[str, Any], received_ts_ms: int | None = None) -> list[DataEvent]:
    if message.get("channel") != "ticker":
        return []
    received = received_ts_ms or now_ms()
    data = message.get("data") or []
    events: list[DataEvent] = []
    for ticker in data if isinstance(data, list) else []:
        symbol = ticker.get("symbol")
        if not symbol:
            continue
        payload = dict(ticker)
        for key in ("bid", "ask", "last"):
            if key in payload and payload[key] is not None:
                payload[key] = float(payload[key])
        events.append(
            DataEvent(
                source="kraken",
                event_type=EventType.KRAKEN_TICKER,
                event_ts_ms=None,
                received_ts_ms=received,
                key=str(symbol).lower(),
                payload=payload,
            )
        )
    return events


async def run_kraken_ticker(
    bus: EventBus,
    symbols: Iterable[str] = ("BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"),
    reconnect_delay: float = 2.0,
) -> None:
    subscription = kraken_ticker_subscription(symbols)
    while True:
        try:
            async with websockets.connect(KRAKEN_WS, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(subscription))
                async for raw in ws:
                    for event in normalize_kraken_message(json.loads(raw)):
                        await bus.publish(event)
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="kraken",
                    event_type=EventType.SOURCE_HEALTH,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"ok": False, "error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)

