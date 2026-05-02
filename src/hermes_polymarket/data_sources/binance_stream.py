"""Binance public stream normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


def binance_combined_stream_url(symbols: Iterable[str]) -> str:
    streams: list[str] = []
    for symbol in symbols:
        sym = symbol.lower()
        streams.extend([f"{sym}@aggTrade", f"{sym}@bookTicker", f"{sym}@kline_1s"])
    if not streams:
        raise ValueError("symbols cannot be empty")
    return f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"


def normalize_binance_message(message: dict[str, Any], received_ts_ms: int | None = None) -> DataEvent | None:
    data = message.get("data") or message
    if not isinstance(data, dict):
        return None
    received = received_ts_ms or now_ms()
    event = data.get("e")
    if event == "aggTrade":
        return DataEvent(
            source="binance",
            event_type=EventType.BINANCE_TRADE,
            event_ts_ms=int(data.get("T") or data.get("E") or 0),
            received_ts_ms=received,
            key=str(data["s"]).lower(),
            payload={
                "symbol": data["s"],
                "price": float(data["p"]),
                "qty": float(data["q"]),
                "trade_ts": data.get("T"),
                "event_ts": data.get("E"),
                "maker_side": data.get("m"),
            },
        )
    if event == "kline":
        kline = data.get("k") or {}
        return DataEvent(
            source="binance",
            event_type=EventType.BINANCE_KLINE,
            event_ts_ms=int(data.get("E") or 0),
            received_ts_ms=received,
            key=str(kline["s"]).lower(),
            payload={
                "symbol": kline["s"],
                "interval": kline["i"],
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": float(kline["c"]),
                "volume": float(kline["v"]),
                "is_closed": bool(kline["x"]),
                "start_ts": kline["t"],
                "end_ts": kline["T"],
            },
        )
    if {"u", "s", "b", "B", "a", "A"}.issubset(data):
        return DataEvent(
            source="binance",
            event_type=EventType.BINANCE_BOOK_TICKER,
            event_ts_ms=None,
            received_ts_ms=received,
            key=str(data["s"]).lower(),
            payload={
                "symbol": data["s"],
                "best_bid": float(data["b"]),
                "best_bid_qty": float(data["B"]),
                "best_ask": float(data["a"]),
                "best_ask_qty": float(data["A"]),
                "update_id": int(data["u"]),
            },
        )
    return None


async def run_binance_stream(
    bus: EventBus,
    symbols: Iterable[str] = ("btcusdt", "ethusdt", "solusdt", "xrpusdt"),
    reconnect_delay: float = 2.0,
) -> None:
    url = binance_combined_stream_url(symbols)
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                async for raw in ws:
                    event = normalize_binance_message(json.loads(raw))
                    if event is not None:
                        await bus.publish(event)
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="binance",
                    event_type=EventType.SOURCE_HEALTH,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"ok": False, "error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)

