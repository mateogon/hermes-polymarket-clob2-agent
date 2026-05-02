"""Base event contracts for data source adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class EventType(str, Enum):
    POLY_BOOK = "poly_book"
    POLY_PRICE_CHANGE = "poly_price_change"
    POLY_BEST_BID_ASK = "poly_best_bid_ask"
    POLY_LAST_TRADE = "poly_last_trade"
    POLY_MARKET_RESOLVED = "poly_market_resolved"
    POLY_TICK_SIZE_CHANGE = "poly_tick_size_change"
    POLY_NEW_MARKET = "poly_new_market"
    RTDS_CRYPTO_PRICE = "rtds_crypto_price"
    BINANCE_TRADE = "binance_trade"
    BINANCE_BOOK_TICKER = "binance_book_ticker"
    BINANCE_KLINE = "binance_kline"
    COINBASE_TICKER = "coinbase_ticker"
    KRAKEN_TICKER = "kraken_ticker"
    WALLET_TRADE = "wallet_trade"
    WEATHER_FORECAST = "weather_forecast"
    METAR = "metar"
    TAF = "taf"
    NEWS_EVENT = "news_event"
    SEC_FILING = "sec_filing"
    MACRO_OBSERVATION = "macro_observation"
    SOURCE_HEALTH = "source_health"


@dataclass(frozen=True)
class DataEvent:
    source: str
    event_type: EventType
    event_ts_ms: int | None
    received_ts_ms: int
    key: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def latency_ms(self) -> int | None:
        if self.event_ts_ms is None:
            return None
        return self.received_ts_ms - self.event_ts_ms


def now_ms() -> int:
    return int(time() * 1000)
