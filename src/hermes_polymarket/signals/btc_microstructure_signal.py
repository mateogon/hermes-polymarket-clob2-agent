"""Paper-only BTC microstructure signal helpers."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.signals.base import Signal


@dataclass(frozen=True)
class BtcIndicators:
    rsi: float
    momentum_1m: float
    momentum_5m: float
    vwap_deviation: float
    sma_crossover: float
    market_skew: float


def make_btc_signal(market_id: str, indicators: BtcIndicators) -> Signal:
    votes = [
        -1 if indicators.rsi > 70 else 1 if indicators.rsi < 30 else 0,
        1 if indicators.momentum_1m + indicators.momentum_5m > 0 else -1,
        1 if indicators.vwap_deviation > 0 else -1,
        1 if indicators.sma_crossover > 0 else -1,
    ]
    score = sum(votes) / len(votes) - indicators.market_skew
    p_up = min(0.65, max(0.35, 0.5 + score * 0.08))
    outcome = "yes" if p_up >= 0.5 else "no"
    p = p_up if outcome == "yes" else 1.0 - p_up
    confidence = min(0.6, 0.25 + abs(score) * 0.1)
    return Signal(
        market_id=market_id,
        outcome=outcome,
        model_probability=p,
        confidence=confidence,
        reason="Directional BTC microstructure signal for paper mode only",
        sources=("btc_microstructure",),
    )

