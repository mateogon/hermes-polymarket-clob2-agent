"""Paper execution engine."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.polymarket.types import MarketMetadata, OrderBook, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class PaperTradeResult:
    accepted: bool
    reason: str
    trade_id: int | None = None
    shares: float = 0.0
    avg_price: float = 0.0


class PaperEngine:
    def __init__(self, db: Database, validator: OrderValidator):
        self.db = db
        self.validator = validator

    def exposure(self, bankroll: float) -> ExposureSnapshot:
        positions = self.db.open_positions()
        portfolio_exposure = sum(float(row["total_cost"]) for row in positions)
        return ExposureSnapshot(
            bankroll=bankroll,
            open_positions=len(positions),
            market_exposure_usd=0.0,
            portfolio_exposure_usd=portfolio_exposure,
        )

    def buy(self, proposal: TradeProposal, metadata: MarketMetadata, book: OrderBook, bankroll: float) -> PaperTradeResult:
        validation = self.validator.validate(proposal, metadata, book, self.exposure(bankroll))
        if not validation.decision.allowed:
            self.db.add_journal("paper_rejected", validation.decision.explanation, {"reason": validation.decision.reason})
            return PaperTradeResult(False, validation.decision.reason)

        fill = simulate_buy_fill(book, validation.decision.capped_size_usd, order_type="fok")
        account = self.db.account()
        total_out = fill.total_cost + fill.fee
        if total_out > float(account["cash"]):
            return PaperTradeResult(False, "insufficient_paper_cash")
        self.db.update_cash(float(account["cash"]) - total_out)
        trade_id = self.db.insert_trade(
            {
                "mode": "paper",
                "market_id": proposal.market_id,
                "condition_id": proposal.condition_id,
                "token_id": proposal.token_id,
                "outcome": proposal.outcome,
                "side": "buy",
                "avg_price": fill.avg_price,
                "shares": fill.total_shares,
                "amount_usd": fill.total_cost,
                "fee": fill.fee,
                "slippage": fill.slippage,
                "signal_reason": proposal.reason,
            }
        )
        self.db.upsert_position(
            market_id=proposal.market_id,
            condition_id=proposal.condition_id,
            token_id=proposal.token_id,
            outcome=proposal.outcome,
            shares=fill.total_shares,
            cost=total_out,
            avg_price=fill.avg_price,
        )
        self.db.add_journal("paper_trade", "Paper trade accepted", {"trade_id": trade_id})
        return PaperTradeResult(True, "accepted", trade_id, fill.total_shares, fill.avg_price)

