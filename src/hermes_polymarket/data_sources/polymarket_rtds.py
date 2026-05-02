"""Polymarket RTDS crypto price event normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


RTDS_WS = "wss://ws-live-data.polymarket.com"


def normalize_rtds_message(message: dict[str, Any], received_ts_ms: int | None = None) -> DataEvent | None:
    if message.get("topic") != "crypto_prices":
        return None
    payload = message.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    symbol = str(payload.get("symbol") or "").lower()
    if not symbol:
        return None
    raw_ts = payload.get("timestamp") or message.get("timestamp")
    try:
        event_ts_ms = int(float(raw_ts)) if raw_ts is not None else None
    except (TypeError, ValueError):
        event_ts_ms = None
    return DataEvent(
        source="polymarket_rtds",
        event_type=EventType.RTDS_CRYPTO_PRICE,
        event_ts_ms=event_ts_ms,
        received_ts_ms=received_ts_ms or now_ms(),
        key=symbol,
        payload=payload,
    )


async def _keepalive(ws: Any) -> None:
    while True:
        await asyncio.sleep(5)
        await ws.send("PING")


async def run_polymarket_rtds_crypto(
    bus: EventBus,
    symbols: Iterable[str] = ("btcusdt", "ethusdt", "solusdt", "xrpusdt"),
    reconnect_delay: float = 2.0,
) -> None:
    filters = ",".join(s.lower() for s in symbols)
    subscription = {
        "action": "subscribe",
        "subscriptions": [{"topic": "crypto_prices", "type": "update", "filters": filters}],
    }

    while True:
        try:
            async with websockets.connect(RTDS_WS, ping_interval=None) as ws:
                await ws.send(json.dumps(subscription))
                await bus.publish(
                    DataEvent(
                        source="polymarket_rtds",
                        event_type=EventType.SOURCE_HEALTH,
                        event_ts_ms=None,
                        received_ts_ms=now_ms(),
                        key="connected",
                        payload={"ok": True, "subscription": subscription},
                    )
                )
                keepalive = asyncio.create_task(_keepalive(ws))
                try:
                    async for raw in ws:
                        if raw == "PONG":
                            await bus.publish(
                                DataEvent(
                                    source="polymarket_rtds",
                                    event_type=EventType.SOURCE_HEALTH,
                                    event_ts_ms=None,
                                    received_ts_ms=now_ms(),
                                    key="pong",
                                    payload={"ok": True},
                                )
                            )
                            continue
                        event = normalize_rtds_message(json.loads(raw))
                        if event is not None:
                            await bus.publish(event)
                finally:
                    keepalive.cancel()
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="polymarket_rtds",
                    event_type=EventType.SOURCE_HEALTH,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"ok": False, "error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)
