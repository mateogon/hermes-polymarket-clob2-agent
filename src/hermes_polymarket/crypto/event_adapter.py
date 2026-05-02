"""Adapt normalized data events into crypto latency recorder inputs."""

from __future__ import annotations

from typing import Any

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.signals.source_consensus import PriceReading


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coinbase_symbol(product_id: str) -> str:
    return product_id.replace("-", "").lower().replace("usd", "usdt")


def _kraken_symbol(symbol: str) -> str:
    return symbol.replace("/", "").lower().replace("usd", "usdt")


def price_reading_from_event(event: DataEvent) -> PriceReading | None:
    payload = event.payload

    if event.event_type == EventType.BINANCE_TRADE:
        price = _float_or_none(payload.get("price"))
        if price is None:
            return None
        return PriceReading("binance", event.key.lower(), price, event.received_ts_ms, event.latency_ms)

    if event.event_type == EventType.BINANCE_BOOK_TICKER:
        bid = _float_or_none(payload.get("best_bid"))
        ask = _float_or_none(payload.get("best_ask"))
        if bid is None or ask is None:
            return None
        return PriceReading("binance", event.key.lower(), (bid + ask) / 2.0, event.received_ts_ms, event.latency_ms)

    if event.event_type == EventType.RTDS_CRYPTO_PRICE:
        raw_price = payload.get("price") or payload.get("value") or payload.get("last")
        price = _float_or_none(raw_price)
        if price is None:
            return None
        return PriceReading("polymarket_rtds", event.key.lower(), price, event.received_ts_ms, event.latency_ms)

    if event.event_type == EventType.COINBASE_TICKER:
        product_id = str(payload.get("product_id") or event.key)
        price = _float_or_none(payload.get("price"))
        if price is None:
            return None
        return PriceReading("coinbase", _coinbase_symbol(product_id), price, event.received_ts_ms, event.latency_ms)

    if event.event_type == EventType.KRAKEN_TICKER:
        price = _float_or_none(payload.get("last") or payload.get("ask") or payload.get("bid"))
        if price is None:
            return None
        return PriceReading("kraken", _kraken_symbol(event.key), price, event.received_ts_ms, event.latency_ms)

    return None


def bbo_from_event(event: DataEvent) -> tuple[str, dict[str, Any]] | None:
    if event.event_type != EventType.POLY_BEST_BID_ASK:
        return None
    return event.key, event.payload
