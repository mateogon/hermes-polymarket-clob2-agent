"""Simple strike-aware fair value estimates for paper-only research."""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt


@dataclass(frozen=True)
class StrikeFairValue:
    probability_yes: float
    distance_pct: float
    seconds_to_expiry: float
    reason: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "probability_yes": self.probability_yes,
            "distance_pct": self.distance_pct,
            "seconds_to_expiry": self.seconds_to_expiry,
            "reason": self.reason,
        }


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def fair_value_above_strike(
    *,
    current_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    annualized_vol: float = 0.60,
) -> StrikeFairValue:
    if current_price <= 0 or strike_price <= 0:
        return StrikeFairValue(0.5, 0.0, seconds_to_expiry, "invalid_price")

    distance = (current_price - strike_price) / strike_price
    year_fraction = max(seconds_to_expiry, 1.0) / 31_536_000
    sigma = max(annualized_vol * sqrt(year_fraction), 1e-6)
    p_above = normal_cdf(distance / sigma)

    return StrikeFairValue(
        probability_yes=max(0.01, min(0.99, p_above)),
        distance_pct=distance * 100.0,
        seconds_to_expiry=seconds_to_expiry,
        reason="diffusion_approx",
    )


def fair_value_below_strike(
    *,
    current_price: float,
    strike_price: float,
    seconds_to_expiry: float,
    annualized_vol: float = 0.60,
) -> StrikeFairValue:
    above = fair_value_above_strike(
        current_price=current_price,
        strike_price=strike_price,
        seconds_to_expiry=seconds_to_expiry,
        annualized_vol=annualized_vol,
    )
    return StrikeFairValue(
        probability_yes=1.0 - above.probability_yes,
        distance_pct=above.distance_pct,
        seconds_to_expiry=seconds_to_expiry,
        reason="diffusion_approx_below",
    )
