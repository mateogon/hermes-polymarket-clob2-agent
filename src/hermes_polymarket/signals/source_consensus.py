"""Consensus pricing across public crypto sources."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class PriceReading:
    source: str
    symbol: str
    price: float
    received_ts_ms: int
    latency_ms: int | None = None


@dataclass(frozen=True)
class ConsensusPrice:
    symbol: str
    price: float
    sources: tuple[str, ...]
    max_deviation_pct: float
    stale_sources: tuple[str, ...]


def consensus_price(
    readings: list[PriceReading],
    *,
    now_ms: int,
    max_age_ms: int = 2500,
    max_deviation_pct_allowed: float = 0.25,
    min_sources: int = 2,
) -> ConsensusPrice | None:
    fresh = [reading for reading in readings if now_ms - reading.received_ts_ms <= max_age_ms]
    stale = tuple(reading.source for reading in readings if now_ms - reading.received_ts_ms > max_age_ms)
    if len(fresh) < min_sources:
        return None

    prices = [reading.price for reading in fresh]
    center = median(prices)
    if center <= 0:
        return None
    max_deviation_pct = max(abs(price - center) / center * 100 for price in prices)
    if max_deviation_pct > max_deviation_pct_allowed:
        return None

    return ConsensusPrice(
        symbol=fresh[0].symbol,
        price=center,
        sources=tuple(sorted({reading.source for reading in fresh})),
        max_deviation_pct=max_deviation_pct,
        stale_sources=stale,
    )
