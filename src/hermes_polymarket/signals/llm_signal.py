"""LLM-assisted signal proposal helpers."""

from __future__ import annotations

from hermes_polymarket.signals.base import Signal


def make_llm_signal(market_id: str, outcome: str, raw_probability: float, rationale: str, citations: list[str]) -> Signal:
    if not rationale.strip() or not citations:
        raise ValueError("LLM signals require rationale and citations")
    return Signal(
        market_id=market_id,
        outcome=outcome,
        model_probability=min(0.95, max(0.05, raw_probability)),
        confidence=0.25,
        reason=f"LLM proposal only: {rationale[:240]}",
        sources=tuple(citations),
    )

