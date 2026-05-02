"""Paper opportunity simulation for crypto latency events."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.types import MarketMetadata, OrderBook, TokenInfo, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot


@dataclass(frozen=True)
class CryptoLatencyOpportunity:
    allowed: bool
    reason: str
    fill_status: str
    avg_price: float
    shares: float
    token_id: str
    outcome: str


def simulate_crypto_latency_entry(
    *,
    validator: OrderValidator,
    metadata: MarketMetadata,
    token: TokenInfo,
    book: OrderBook,
    market_id: str,
    amount_usd: float,
    model_probability: float,
    exposure: ExposureSnapshot,
) -> CryptoLatencyOpportunity:
    proposal = TradeProposal(
        market_id=market_id,
        condition_id=metadata.condition_id,
        token_id=token.token_id,
        outcome=token.outcome,
        side="buy",
        amount_usd=amount_usd,
        model_probability=model_probability,
        confidence=0.35,
        reason="crypto latency paper opportunity",
    )
    result = validator.validate(proposal, metadata, book, exposure)
    return CryptoLatencyOpportunity(
        allowed=result.decision.allowed,
        reason=result.decision.reason,
        fill_status=result.fill_status,
        avg_price=result.avg_price,
        shares=result.shares,
        token_id=token.token_id,
        outcome=token.outcome,
    )
