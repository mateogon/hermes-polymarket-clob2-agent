from hermes_polymarket.backtest.crypto_latency_opportunity import simulate_crypto_latency_entry
from hermes_polymarket.config import load_settings
from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager


def test_crypto_latency_opportunity_passes_through_risk_manager():
    settings = load_settings()
    token = TokenInfo("t", "Yes")
    metadata = MarketMetadata("c", 0.01, 1.0, (token,), FeeDetails())
    book = OrderBook("t", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))
    result = simulate_crypto_latency_entry(
        validator=OrderValidator(RiskManager(settings)),
        metadata=metadata,
        token=token,
        book=book,
        market_id="m",
        amount_usd=5,
        model_probability=0.7,
        exposure=ExposureSnapshot(bankroll=1000),
    )
    assert result.fill_status == "filled"
    assert result.token_id == "t"
