"""Dry-run with deterministic safe fixture data.

The CLI accepts market inputs, but this script uses fixture metadata/orderbook
until a real market resolver is wired into strategy flows.
"""

from __future__ import annotations

from hermes_polymarket.config import Settings, load_settings
from hermes_polymarket.execution.dry_run_executor import DryRunExecutor
from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager


def run_dry_run(settings: Settings | None, market: str, side: str, amount: float) -> dict:
    settings = settings or load_settings()
    outcome = side.lower()
    token = TokenInfo(token_id=f"fixture-{outcome}", outcome=outcome)
    metadata = MarketMetadata(
        condition_id=market,
        min_tick_size=0.01,
        min_order_size=1.0,
        tokens=(token,),
        fee_details=FeeDetails(),
    )
    book = OrderBook(
        token_id=token.token_id,
        bids=(OrderBookLevel(0.49, 100.0), OrderBookLevel(0.48, 100.0)),
        asks=(OrderBookLevel(0.50, 100.0), OrderBookLevel(0.51, 100.0)),
    )
    proposal = TradeProposal(
        market_id=market,
        condition_id=market,
        token_id=token.token_id,
        outcome=outcome,
        side="buy",
        amount_usd=amount,
        model_probability=0.58,
        confidence=0.5,
        reason="dry-run fixture proposal",
    )
    validator = OrderValidator(RiskManager(settings))
    result = DryRunExecutor(validator).run(
        proposal,
        metadata,
        book,
        ExposureSnapshot(bankroll=settings.initial_bankroll),
    )
    return {
        "market": market,
        "side": side.upper(),
        "amount": amount,
        "fill_status": result.fill_status,
        "avg_price": result.avg_price,
        "shares": result.shares,
        "decision": {
            "allowed": result.decision.allowed,
            "reason": result.decision.reason,
            "explanation": result.decision.explanation,
            "capped_size_usd": result.decision.capped_size_usd,
        },
        "posted_order": False,
    }


if __name__ == "__main__":
    print(run_dry_run(load_settings(), "fixture-market", "YES", 5.0))
