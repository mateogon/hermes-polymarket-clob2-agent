"""Polymarket public market WebSocket normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


POLY_MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


EVENT_MAP = {
    "book": EventType.POLY_BOOK,
    "price_change": EventType.POLY_PRICE_CHANGE,
    "best_bid_ask": EventType.POLY_BEST_BID_ASK,
    "last_trade_price": EventType.POLY_LAST_TRADE,
    "market_resolved": EventType.POLY_MARKET_RESOLVED,
    "tick_size_change": EventType.POLY_TICK_SIZE_CHANGE,
    "new_market": EventType.POLY_NEW_MARKET,
}


def market_subscription(asset_ids: Iterable[str]) -> dict[str, Any]:
    assets = [str(asset_id) for asset_id in asset_ids if asset_id]
    if not assets:
        raise ValueError("asset_ids cannot be empty")
    return {"assets_ids": assets, "type": "market", "custom_feature_enabled": True}


def _event_ts(payload: dict[str, Any]) -> int | None:
    raw = payload.get("timestamp") or payload.get("event_timestamp")
    try:
        return int(float(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def normalize_market_ws_payload(payload: Any, received_ts_ms: int | None = None) -> list[DataEvent]:
    if payload == "PONG":
        return []
    messages = payload if isinstance(payload, list) else [payload]
    events: list[DataEvent] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        event_type = EVENT_MAP.get(str(message.get("event_type") or ""))
        if event_type is None:
            continue
        if event_type == EventType.POLY_PRICE_CHANGE and isinstance(message.get("price_changes"), list):
            market = message.get("market")
            event_ts_ms = _event_ts(message)
            for change in message["price_changes"]:
                if not isinstance(change, dict):
                    continue
                payload_for_asset = dict(change)
                payload_for_asset["market"] = market
                payload_for_asset["event_type"] = "price_change"
                payload_for_asset["removed"] = str(change.get("size")) == "0"
                events.append(
                    DataEvent(
                        source="polymarket_market_ws",
                        event_type=event_type,
                        event_ts_ms=event_ts_ms,
                        received_ts_ms=received_ts_ms or now_ms(),
                        key=str(change.get("asset_id") or "unknown"),
                        payload=payload_for_asset,
                    )
                )
            continue
        key = str(message.get("asset_id") or message.get("market") or message.get("condition_id") or "unknown")
        events.append(
            DataEvent(
                source="polymarket_market_ws",
                event_type=event_type,
                event_ts_ms=_event_ts(message),
                received_ts_ms=received_ts_ms or now_ms(),
                key=key,
                payload=message,
            )
        )
    return events


async def run_polymarket_market_ws(
    bus: EventBus,
    asset_ids: Iterable[str],
    reconnect_delay: float = 2.0,
) -> None:
    subscription = market_subscription(asset_ids)
    while True:
        try:
            async with websockets.connect(POLY_MARKET_WS, ping_interval=None) as ws:
                await ws.send(json.dumps(subscription))
                keepalive = asyncio.create_task(_keepalive(ws))
                try:
                    async for raw in ws:
                        if raw == "PONG":
                            continue
                        for event in normalize_market_ws_payload(json.loads(raw)):
                            await bus.publish(event)
                finally:
                    keepalive.cancel()
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="polymarket_market_ws",
                    event_type=EventType.SOURCE_HEALTH,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"ok": False, "error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)


async def _keepalive(ws: Any) -> None:
    while True:
        await asyncio.sleep(10)
        await ws.send("PING")
