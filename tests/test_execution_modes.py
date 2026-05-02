import pytest

from hermes_polymarket.config import load_settings
from hermes_polymarket.execution.dry_run_executor import DryRunExecutor
from hermes_polymarket.execution.live_executor import LiveExecutor
from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo, TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager


def test_dry_run_validates_without_posting():
    settings = load_settings()
    token = TokenInfo("t", "yes")
    metadata = MarketMetadata("c", 0.01, 1.0, (token,), FeeDetails())
    book = OrderBook("t", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))
    proposal = TradeProposal("m", "c", "t", "yes", "buy", 5.0, 0.7, 0.5, "dry")
    result = DryRunExecutor(OrderValidator(RiskManager(settings))).run(
        proposal, metadata, book, ExposureSnapshot(bankroll=1000)
    )
    assert result.decision.allowed is True


def test_sell_validation_requires_share_quantity():
    settings = load_settings()
    token = TokenInfo("t", "yes")
    metadata = MarketMetadata("c", 0.01, 1.0, (token,), FeeDetails())
    book = OrderBook("t", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))
    proposal = TradeProposal("m", "c", "t", "yes", "sell", 5.0, 0.7, 0.5, "dry")
    result = DryRunExecutor(OrderValidator(RiskManager(settings))).run(
        proposal, metadata, book, ExposureSnapshot(bankroll=1000)
    )
    assert result.decision.allowed is False
    assert result.decision.reason == "invalid_sell_shares"


def test_sell_validation_uses_sell_shares():
    settings = load_settings()
    token = TokenInfo("t", "yes")
    metadata = MarketMetadata("c", 0.01, 1.0, (token,), FeeDetails())
    book = OrderBook("t", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))
    proposal = TradeProposal("m", "c", "t", "yes", "sell", 0.0, 0.7, 0.5, "dry", sell_shares=10.0)
    result = DryRunExecutor(OrderValidator(RiskManager(settings))).run(
        proposal, metadata, book, ExposureSnapshot(bankroll=1000)
    )
    assert result.fill_status == "filled"
    assert result.shares == 10.0


def test_live_executor_refuses_by_default():
    settings = load_settings()
    executor = LiveExecutor(settings)
    gate = executor.check_gate(live_flag=True)
    assert gate.allowed is False
    with pytest.raises(PermissionError):
        executor.place_order(live_flag=True)
