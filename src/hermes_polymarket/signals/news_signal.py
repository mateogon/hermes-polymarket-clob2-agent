"""News signal proposal helpers."""

from __future__ import annotations

from hermes_polymarket.signals.base import Signal


def make_news_signal(market_id: str, outcome: str, probability: float, evidence: str) -> Signal:
    if not evidence.strip():
        raise ValueError("News signals require evidence")
    return Signal(
        market_id=market_id,
        outcome=outcome,
        model_probability=min(0.95, max(0.05, probability)),
        confidence=0.35,
        reason=f"News proposal with evidence: {evidence[:240]}",
        sources=("news",),
    )

