"""Typed representation for Campaign v2 paper signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CampaignV2Signal:
    run_id: str
    symbol: str
    condition_id: str
    token_id: str
    direction: str
    outcome: str
    external_move_pct: float
    market_score: float
    stale_quote_allowed: bool
    stale_quote_reason: str
    fair_value_probability: float
    fair_value_edge: float
    executable_price: float | None
    risk_allowed: bool
    risk_reason: str
    final_action: str
    payload: dict[str, Any]
