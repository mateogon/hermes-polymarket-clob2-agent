"""Paper-only fair value estimates for target-hit crypto markets."""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt

from hermes_polymarket.crypto.strike_fair_value import normal_cdf


@dataclass(frozen=True)
class MultiStrikeFairValue:
    probability_yes: float
    distance_pct: float
    seconds_to_expiry: float
    direction: str
    reason: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "probability_yes": self.probability_yes,
            "distance_pct": self.distance_pct,
            "seconds_to_expiry": self.seconds_to_expiry,
            "direction": self.direction,
            "reason": self.reason,
        }


def fair_value_target_hit(
    *,
    current_price: float,
    target_price: float,
    seconds_to_expiry: float,
    annualized_vol: float = 0.80,
) -> MultiStrikeFairValue:
    if current_price <= 0 or target_price <= 0:
        return MultiStrikeFairValue(0.5, 0.0, seconds_to_expiry, "unknown", "invalid_price")

    distance_pct = (current_price - target_price) / target_price * 100.0
    year_fraction = max(seconds_to_expiry, 1.0) / 31_536_000
    sigma_t = max(annualized_vol * sqrt(year_fraction), 1e-6)
    direction = "above" if target_price >= current_price else "below"

    if direction == "above":
        if current_price >= target_price:
            probability = 0.99
            reason = "target_already_crossed"
        else:
            z = log(target_price / current_price) / sigma_t
            probability = 2.0 * (1.0 - normal_cdf(z))
            reason = "barrier_touch_diffusion_approx"
    else:
        if current_price <= target_price:
            probability = 0.99
            reason = "target_already_crossed"
        else:
            z = log(target_price / current_price) / sigma_t
            probability = 2.0 * normal_cdf(z)
            reason = "barrier_touch_diffusion_approx"

    return MultiStrikeFairValue(
        probability_yes=max(0.01, min(0.99, probability)),
        distance_pct=distance_pct,
        seconds_to_expiry=seconds_to_expiry,
        direction=direction,
        reason=reason,
    )
