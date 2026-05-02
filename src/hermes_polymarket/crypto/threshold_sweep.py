"""Threshold sweep helpers for recorded consensus prices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdSweepResult:
    symbol: str
    threshold_pct: float
    hits: int
    max_move_pct: float


def count_threshold_hits(
    *,
    symbol: str,
    prices: list[tuple[int, float]],
    thresholds_pct: list[float],
    lookback_ms: int,
    cooldown_ms: int = 0,
) -> list[ThresholdSweepResult]:
    hits = {threshold: 0 for threshold in thresholds_pct}
    max_moves = {threshold: 0.0 for threshold in thresholds_pct}
    last_hit_ts = {threshold: -(10**18) for threshold in thresholds_pct}
    ordered = sorted((ts_ms, price) for ts_ms, price in prices if price > 0)

    for idx, (ts_ms, price) in enumerate(ordered):
        window = [
            prior_price
            for prior_ts, prior_price in ordered[:idx]
            if 0 < ts_ms - prior_ts <= lookback_ms
        ]
        if not window:
            continue

        low = min(window)
        high = max(window)
        references = [ref for ref in (low, high) if ref > 0]
        if not references:
            continue
        move_pct = max(abs((price - reference) / reference * 100.0) for reference in references)

        for threshold in thresholds_pct:
            max_moves[threshold] = max(max_moves[threshold], move_pct)
            if move_pct >= threshold and ts_ms - last_hit_ts[threshold] >= cooldown_ms:
                hits[threshold] += 1
                last_hit_ts[threshold] = ts_ms

    return [
        ThresholdSweepResult(symbol=symbol, threshold_pct=threshold, hits=hits[threshold], max_move_pct=max_moves[threshold])
        for threshold in thresholds_pct
    ]
