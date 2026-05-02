"""Simple contract-state fair-value model for up/down crypto markets."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FairValueDecision:
    allowed: bool
    reason: str
    fair_value: float
    executable_price: float
    edge: float
    direction: str

    def to_dict(self) -> dict:
        return asdict(self)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fair_value_up(
    *,
    current_price: float,
    reference_price: float,
    seconds_to_expiry: float,
    realized_vol_estimate: float = 1.0,
    distance_scale_pct: float = 0.25,
    min_probability: float = 0.10,
    max_probability: float = 0.90,
    time_decay_enabled: bool = True,
) -> float:
    if reference_price <= 0:
        return 0.5
    distance_pct = (current_price - reference_price) / reference_price * 100.0
    scale = max(distance_scale_pct * max(realized_vol_estimate, 0.01), 0.01)
    raw = 0.5 + 0.25 * (distance_pct / scale)
    if time_decay_enabled:
        urgency = _clip(900.0 / max(seconds_to_expiry, 1.0), 0.25, 3.0)
        raw = 0.5 + (raw - 0.5) * urgency
    return _clip(raw, min_probability, max_probability)


def fair_value_for_direction(
    *,
    direction: str,
    current_price: float,
    reference_price: float,
    seconds_to_expiry: float,
    realized_vol_estimate: float = 1.0,
    distance_scale_pct: float = 0.25,
    min_probability: float = 0.10,
    max_probability: float = 0.90,
) -> float:
    up = fair_value_up(
        current_price=current_price,
        reference_price=reference_price,
        seconds_to_expiry=seconds_to_expiry,
        realized_vol_estimate=realized_vol_estimate,
        distance_scale_pct=distance_scale_pct,
        min_probability=min_probability,
        max_probability=max_probability,
    )
    return up if direction == "up" else 1.0 - up


def evaluate_fair_value_edge(
    *,
    direction: str,
    current_price: float,
    reference_price: float,
    seconds_to_expiry: float,
    executable_price: float,
    min_edge: float = 0.03,
    realized_vol_estimate: float = 1.0,
    distance_scale_pct: float = 0.25,
    min_probability: float = 0.10,
    max_probability: float = 0.90,
) -> FairValueDecision:
    fair = fair_value_for_direction(
        direction=direction,
        current_price=current_price,
        reference_price=reference_price,
        seconds_to_expiry=seconds_to_expiry,
        realized_vol_estimate=realized_vol_estimate,
        distance_scale_pct=distance_scale_pct,
        min_probability=min_probability,
        max_probability=max_probability,
    )
    edge = fair - executable_price
    return FairValueDecision(
        allowed=edge >= min_edge,
        reason="fair_value_edge" if edge >= min_edge else "edge_below_min",
        fair_value=fair,
        executable_price=executable_price,
        edge=edge,
        direction=direction,
    )
