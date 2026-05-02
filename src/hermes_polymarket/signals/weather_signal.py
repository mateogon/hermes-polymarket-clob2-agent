"""Conservative weather signal helpers."""

from __future__ import annotations

from statistics import mean, pstdev

from hermes_polymarket.signals.base import Signal


def bucket_probability(samples: list[float], low: float | None, high: float | None) -> float:
    if not samples:
        return 0.5
    count = 0
    for sample in samples:
        if low is not None and sample < low:
            continue
        if high is not None and sample > high:
            continue
        count += 1
    raw = count / len(samples)
    return min(0.95, max(0.05, raw))


def make_weather_signal(market_id: str, outcome: str, samples: list[float], low: float | None, high: float | None) -> Signal:
    p = bucket_probability(samples, low, high)
    sigma = pstdev(samples) if len(samples) > 1 else 0.0
    center = mean(samples) if samples else 0.0
    confidence = min(0.8, max(0.1, 1.0 / (1.0 + sigma)))
    return Signal(
        market_id=market_id,
        outcome=outcome,
        model_probability=p,
        confidence=confidence,
        reason=f"Weather bucket probability from ensemble center={center:.2f} sigma={sigma:.2f}",
        sources=("weather_ensemble",),
    )

