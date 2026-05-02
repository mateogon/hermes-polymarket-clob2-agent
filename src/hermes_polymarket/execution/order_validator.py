"""Shared validation for paper, dry-run, and live paths."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.polymarket.orderbook import simulate_buy_fill, simulate_sell_fill
from hermes_polymarket.polymarket.types import MarketMetadata, OrderBook, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskDecision, RiskManager


@dataclass(frozen=True)
class ValidationResult:
    decision: RiskDecision
    fill_status: str
    avg_price: float
    shares: float


class OrderValidator:
    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager

    def validate(self, proposal: TradeProposal, metadata: MarketMetadata, book: OrderBook, exposure: ExposureSnapshot) -> ValidationResult:
        if proposal.token_id not in {t.token_id for t in metadata.tokens}:
            decision = RiskDecision(False, "token_not_in_market", "Token ID is not part of CLOB market metadata")
            return ValidationResult(decision, "token_not_in_market", 0.0, 0.0)
        if proposal.amount_usd < metadata.min_order_size:
            decision = RiskDecision(False, "min_order_size", "Amount is below CLOB minimum order size")
            return ValidationResult(decision, "min_order_size", 0.0, 0.0)
        fill = simulate_buy_fill(book, proposal.amount_usd, order_type="fok") if proposal.side.lower() == "buy" else simulate_sell_fill(book, proposal.amount_usd, order_type="fok")
        decision = self.risk_manager.evaluate(proposal, book, fill, exposure)
        return ValidationResult(decision, fill.status, fill.avg_price, fill.total_shares)

