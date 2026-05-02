"""Core Polymarket data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TokenInfo:
    token_id: str
    outcome: str


@dataclass(frozen=True)
class FeeDetails:
    rate: float = 0.0
    exponent: float = 1.0
    taker_only: bool = True


@dataclass(frozen=True)
class MarketMetadata:
    condition_id: str
    min_tick_size: float
    min_order_size: float
    tokens: tuple[TokenInfo, ...]
    fee_details: FeeDetails = field(default_factory=FeeDetails)
    neg_risk: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def token_for_outcome(self, outcome: str) -> TokenInfo:
        wanted = outcome.strip().lower()
        aliases = {
            "yes": {"yes", "up", "above", "over", "true"},
            "no": {"no", "down", "below", "under", "false"},
        }
        accepted = aliases.get(wanted, {wanted})
        for token in self.tokens:
            if token.outcome.strip().lower() in accepted:
                return token
        raise KeyError(f"No token for outcome {outcome!r}")


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def best_bid(self) -> float | None:
        return max((level.price for level in self.bids), default=None)

    @property
    def best_ask(self) -> float | None:
        return min((level.price for level in self.asks), default=None)

    @property
    def midpoint(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass(frozen=True)
class Fill:
    price: float
    shares: float
    value: float
    level: int


@dataclass(frozen=True)
class FillResult:
    filled: bool
    avg_price: float
    total_cost: float
    total_shares: float
    fee: float
    slippage: float
    levels_filled: int
    is_partial: bool
    status: str
    fills: tuple[Fill, ...] = ()


@dataclass(frozen=True)
class TradeProposal:
    market_id: str
    condition_id: str
    token_id: str
    outcome: str
    side: str
    amount_usd: float
    model_probability: float
    confidence: float
    reason: str
    sell_shares: float | None = None
    expiry: datetime | None = None
