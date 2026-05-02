"""Coinbase Advanced Trade public ticker normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"


def coinbase_subscriptions(product_ids: Iterable[str]) -> list[dict[str, Any]]:
    products = [str(product_id) for product_id in product_ids if product_id]
    if not products:
        raise ValueError("product_ids cannot be empty")
    return [
        {"type": "subscribe", "channel": "heartbeats"},
        {"type": "subscribe", "channel": "ticker", "product_ids": products},
    ]


def normalize_coinbase_message(message: dict[str, Any], received_ts_ms: int | None = None) -> list[DataEvent]:
    if message.get("channel") != "ticker":
        return []
    received = received_ts_ms or now_ms()
    events: list[DataEvent] = []
    for event in message.get("events", []):
        for ticker in event.get("tickers", []):
            product_id = ticker.get("product_id")
            price = ticker.get("price")
            if product_id is None or price is None:
                continue
            events.append(
                DataEvent(
                    source="coinbase",
                    event_type=EventType.COINBASE_TICKER,
                    event_ts_ms=None,
                    received_ts_ms=received,
                    key=str(product_id).lower(),
                    payload={"product_id": product_id, "price": float(price), "raw": ticker},
                )
            )
    return events


async def run_coinbase_ticker(
    bus: EventBus,
    product_ids: Iterable[str] = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"),
    reconnect_delay: float = 2.0,
) -> None:
    messages = coinbase_subscriptions(product_ids)
    while True:
        try:
            async with websockets.connect(COINBASE_WS, ping_interval=20, ping_timeout=20) as ws:
                for message in messages:
                    await ws.send(json.dumps(message))
                async for raw in ws:
                    for event in normalize_coinbase_message(json.loads(raw)):
                        await bus.publish(event)
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="coinbase",
                    event_type=EventType.SOURCE_HEALTH,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"ok": False, "error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)

