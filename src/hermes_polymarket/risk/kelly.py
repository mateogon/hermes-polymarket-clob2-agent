"""Quarter-Kelly sizing for binary prediction market shares."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KellyResult:
    adjusted_probability: float
    full_kelly: float
    quarter_kelly: float
    edge: float
    size_usd: float


def adjusted_probability(model_probability: float, market_price: float, confidence_discount: float) -> float:
    discount = min(max(confidence_discount, 0.0), 0.5)
    adjusted = market_price + discount * (model_probability - market_price)
    return min(0.95, max(0.05, adjusted))


def quarter_kelly_size(
    *,
    bankroll: float,
    entry_price: float,
    model_probability: float,
    market_price: float | None = None,
    confidence_discount: float = 0.5,
    kelly_fraction: float = 0.25,
) -> KellyResult:
    if entry_price <= 0 or entry_price >= 1 or bankroll <= 0:
        return KellyResult(0.0, 0.0, 0.0, 0.0, 0.0)
    reference_price = entry_price if market_price is None else market_price
    p = adjusted_probability(model_probability, reference_price, confidence_discount)
    b = (1.0 - entry_price) / entry_price
    q = 1.0 - p
    full = (b * p - q) / b if b > 0 else 0.0
    full_positive = max(0.0, full)
    fractional = min(max(kelly_fraction, 0.0), 1.0) * full_positive
    return KellyResult(
        adjusted_probability=p,
        full_kelly=full,
        quarter_kelly=fractional,
        edge=p - entry_price,
        size_usd=bankroll * fractional,
    )

