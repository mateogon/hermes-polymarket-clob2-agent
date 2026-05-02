"""Centralized risk checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from hermes_polymarket.config import Settings
from hermes_polymarket.polymarket.types import FillResult, OrderBook, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.kelly import KellyResult, quarter_kelly_size


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    explanation: str
    kelly: KellyResult | None = None
    capped_size_usd: float = 0.0


class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(
        self,
        proposal: TradeProposal,
        book: OrderBook,
        fill: FillResult,
        exposure: ExposureSnapshot,
    ) -> RiskDecision:
        if proposal.amount_usd <= 0:
            return self._reject("invalid_amount", "Order amount must be positive")
        if proposal.amount_usd > self.settings.max_order_usd:
            return self._reject("max_order_usd", f"Order ${proposal.amount_usd:.2f} exceeds cap ${self.settings.max_order_usd:.2f}")
        if exposure.daily_pnl <= -self.settings.daily_loss_limit_usd:
            return self._reject("daily_loss_limit", "Daily loss limit reached")
        if exposure.open_positions >= self.settings.max_open_positions:
            return self._reject("max_open_positions", "Maximum open positions reached")
        if exposure.market_exposure_usd + proposal.amount_usd > self.settings.max_market_exposure_usd:
            return self._reject("max_market_exposure", "Per-market exposure cap reached")
        max_portfolio = exposure.bankroll * self.settings.max_portfolio_exposure_pct
        if exposure.portfolio_exposure_usd + proposal.amount_usd > max_portfolio:
            return self._reject("max_portfolio_exposure", "Portfolio exposure cap reached")
        if proposal.expiry is not None:
            hours = (proposal.expiry - datetime.now(timezone.utc)).total_seconds() / 3600.0
            if hours < self.settings.min_hours_to_expiry:
                return self._reject("near_expiry", "Market expires before minimum hours-to-expiry")
        if not fill.fills:
            return self._reject(fill.status, "No executable fill available")
        if not fill.filled and fill.is_partial:
            return self._reject("partial_fill", "Partial fill not accepted by risk manager")
        entry_price = fill.avg_price
        if entry_price < self.settings.min_entry_price:
            return self._reject("lottery_ticket", "Entry price below configured floor")
        if entry_price > self.settings.max_entry_price:
            return self._reject("near_certain_price", "Entry price above configured ceiling")
        if abs(fill.slippage) > self.settings.max_slippage:
            return self._reject("max_slippage", "Slippage exceeds configured maximum")
        depth_usd = sum(level.price * level.size for level in book.asks)
        if proposal.side.lower() == "sell":
            depth_usd = sum(level.price * level.size for level in book.bids)
        if depth_usd < self.settings.min_orderbook_depth_usd:
            return self._reject("min_liquidity", "Orderbook depth below configured minimum")

        kelly = quarter_kelly_size(
            bankroll=exposure.bankroll,
            entry_price=entry_price,
            model_probability=proposal.model_probability,
            market_price=entry_price,
            confidence_discount=self.settings.confidence_discount,
            kelly_fraction=self.settings.kelly_fraction,
        )
        if kelly.edge < self.settings.min_edge:
            return RiskDecision(False, "min_edge", "Adjusted edge is below threshold", kelly, 0.0)
        if kelly.edge > self.settings.reject_edge_over:
            return RiskDecision(False, "absurd_edge", "Adjusted edge is too large without manual approval", kelly, 0.0)

        capped = min(kelly.size_usd, self.settings.max_order_usd, proposal.amount_usd)
        if capped <= 0:
            return RiskDecision(False, "kelly_zero", "Kelly sizing produced no position", kelly, 0.0)
        return RiskDecision(True, "allowed", "Order passed risk checks", kelly, capped)

    @staticmethod
    def _reject(reason: str, explanation: str) -> RiskDecision:
        return RiskDecision(False, reason, explanation)

