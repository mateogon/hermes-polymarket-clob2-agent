"""Latest crypto price state from normalized exchange events."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.data_sources.base import DataEvent, EventType


@dataclass(frozen=True)
class CryptoPrice:
    source: str
    symbol: str
    price: float
    received_ts_ms: int


class CryptoPriceState:
    def __init__(self):
        self.latest: dict[tuple[str, str], CryptoPrice] = {}

    def apply(self, event: DataEvent) -> None:
        price = _price_from_event(event)
        if price is None:
            return
        symbol = event.key.lower()
        self.latest[(event.source, symbol)] = CryptoPrice(event.source, symbol, price, event.received_ts_ms)

    def get(self, source: str, symbol: str) -> CryptoPrice | None:
        return self.latest.get((source, symbol.lower()))


def _price_from_event(event: DataEvent) -> float | None:
    if event.event_type == EventType.BINANCE_TRADE:
        return float(event.payload["price"])
    if event.event_type == EventType.BINANCE_BOOK_TICKER:
        return (float(event.payload["best_bid"]) + float(event.payload["best_ask"])) / 2.0
    if event.event_type == EventType.BINANCE_KLINE:
        return float(event.payload["close"])
    if event.event_type in {EventType.COINBASE_TICKER, EventType.KRAKEN_TICKER, EventType.RTDS_CRYPTO_PRICE}:
        raw = event.payload.get("price") or event.payload.get("last")
        return float(raw) if raw is not None else None
    return None

