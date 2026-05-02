"""Threshold sweep helpers for recorded consensus prices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdSweepResult:
    symbol: str
    threshold_pct: float
    hits: int


def count_threshold_hits(
    *,
    symbol: str,
    prices: list[tuple[int, float]],
    thresholds_pct: list[float],
    lookback_ms: int,
) -> list[ThresholdSweepResult]:
    results = {threshold: 0 for threshold in thresholds_pct}
    ordered = sorted(prices)

    for idx, (ts_ms, price) in enumerate(ordered):
        if price <= 0:
            continue

        lookback = [
            prior_price
            for prior_ts, prior_price in ordered[:idx]
            if ts_ms - prior_ts <= lookback_ms
        ]
        if not lookback:
            continue

        reference = lookback[0]
        if reference <= 0:
            continue

        move_pct = abs((price - reference) / reference * 100.0)
        for threshold in thresholds_pct:
            if move_pct >= threshold:
                results[threshold] += 1

    return [
        ThresholdSweepResult(symbol=symbol, threshold_pct=threshold, hits=hits)
        for threshold, hits in results.items()
    ]
