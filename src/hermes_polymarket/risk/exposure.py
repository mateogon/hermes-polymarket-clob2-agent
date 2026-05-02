"""Exposure snapshot types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureSnapshot:
    bankroll: float
    open_positions: int = 0
    daily_pnl: float = 0.0
    market_exposure_usd: float = 0.0
    portfolio_exposure_usd: float = 0.0

