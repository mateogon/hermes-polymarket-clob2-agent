"""Dry-run order validation.

Default mode uses public Gamma discovery plus CLOB orderbooks. Fixture mode is
kept only for deterministic tests and local quality gates.
"""

from __future__ import annotations

from hermes_polymarket.config import Settings, load_settings
from hermes_polymarket.execution.dry_run_executor import DryRunExecutor
from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.polymarket.market_data import MarketData, MarketIdentifierType
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager


def _fixture_order(settings: Settings, market: str, outcome: str, amount: float) -> dict:
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
    return _validate(settings, market, outcome, amount, metadata, token, book, "dry-run fixture proposal", "fixture")


def _validate(
    settings: Settings,
    market: str,
    outcome: str,
    amount: float,
    metadata: MarketMetadata,
    token: TokenInfo,
    book: OrderBook,
    reason: str,
    source: str,
) -> dict:
    proposal = TradeProposal(
        market_id=market,
        condition_id=metadata.condition_id,
        token_id=token.token_id,
        outcome=outcome,
        side="buy",
        amount_usd=amount,
        model_probability=0.58,
        confidence=0.5,
        reason=reason,
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
        "condition_id": metadata.condition_id,
        "token_id": token.token_id,
        "source": source,
        "side": outcome.upper(),
        "amount": amount,
        "fill_status": result.fill_status,
        "avg_price": result.avg_price,
        "shares": result.shares,
        "best_bid": book.best_bid,
        "best_ask": book.best_ask,
        "decision": {
            "allowed": result.decision.allowed,
            "reason": result.decision.reason,
            "explanation": result.decision.explanation,
            "capped_size_usd": result.decision.capped_size_usd,
        },
        "posted_order": False,
    }


def run_dry_run(
    settings: Settings | None,
    market: str,
    side: str,
    amount: float,
    *,
    fixture: bool = False,
    identifier_type: str | None = None,
) -> dict:
    settings = settings or load_settings()
    outcome = side.lower()
    if fixture:
        return _fixture_order(settings, market, outcome, amount)

    clob = ClobV2Client(settings)
    gamma = GammaClient()
    try:
        resolver = MarketData(clob, gamma)
        resolved = resolver.resolve_orderbook(
            market,
            outcome=outcome,
            identifier_type=MarketIdentifierType(identifier_type) if identifier_type else None,
        )
        return _validate(
            settings,
            resolved.market.slug or market,
            outcome,
            amount,
            resolved.market.metadata,
            resolved.token,
            resolved.book,
            "dry-run public market proposal",
            "public",
        )
    finally:
        clob.close()
        gamma.close()


if __name__ == "__main__":
    print(run_dry_run(load_settings(), "fixture-market", "YES", 5.0, fixture=True))
