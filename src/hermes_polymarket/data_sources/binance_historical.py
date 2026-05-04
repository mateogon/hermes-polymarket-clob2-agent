"""Binance public historical candle access for backtests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


BINANCE_REST = "https://api.binance.com"


@dataclass(frozen=True)
class BinanceCandle:
    open_ts_ms: int
    close_ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


class BinanceHistoricalClient:
    def __init__(self, *, base_url: str = BINANCE_REST, timeout: float = 20.0):
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def get_klines(
        self,
        *,
        symbol: str,
        interval: str = "1m",
        start_ts_ms: int,
        end_ts_ms: int,
        limit: int = 1000,
    ) -> list[BinanceCandle]:
        response = self._http.get(
            "/api/v3/klines",
            params={
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_ts_ms,
                "endTime": end_ts_ms,
                "limit": min(max(limit, 1), 1000),
            },
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return []
        return [_parse_kline(row) for row in rows if isinstance(row, list) and len(row) >= 7]

    def get_klines_paginated(
        self,
        *,
        symbol: str,
        interval: str = "1m",
        start_ts_ms: int,
        end_ts_ms: int,
        limit: int = 1000,
    ) -> list[BinanceCandle]:
        candles: list[BinanceCandle] = []
        cursor = start_ts_ms
        while cursor < end_ts_ms:
            page = self.get_klines(
                symbol=symbol,
                interval=interval,
                start_ts_ms=cursor,
                end_ts_ms=end_ts_ms,
                limit=limit,
            )
            if not page:
                break
            candles.extend(page)
            next_cursor = page[-1].close_ts_ms + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(page) < min(max(limit, 1), 1000):
                break
        return candles


def _parse_kline(row: list[Any]) -> BinanceCandle:
    return BinanceCandle(
        open_ts_ms=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_ts_ms=int(row[6]),
    )
