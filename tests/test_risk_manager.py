from hermes_polymarket.config import load_settings
from hermes_polymarket.polymarket.orderbook import parse_orderbook, simulate_buy_fill
from hermes_polymarket.polymarket.types import TradeProposal
from hermes_polymarket.risk.exposure import ExposureSnapshot
from hermes_polymarket.risk.risk_manager import RiskManager


def _book():
    return parse_orderbook(
        "t",
        {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.50", "size": "100"}]},
    )


def _proposal(amount=5.0, model_probability=0.7):
    return TradeProposal(
        market_id="m",
        condition_id="c",
        token_id="t",
        outcome="yes",
        side="buy",
        amount_usd=amount,
        model_probability=model_probability,
        confidence=0.5,
        reason="test",
    )


def test_risk_allows_small_edge_checked_order():
    settings = load_settings()
    book = _book()
    fill = simulate_buy_fill(book, 5.0)
    decision = RiskManager(settings).evaluate(_proposal(), book, fill, ExposureSnapshot(bankroll=1000))
    assert decision.allowed is True
    assert decision.capped_size_usd <= settings.max_order_usd


def test_risk_rejects_max_order():
    settings = load_settings()
    book = _book()
    fill = simulate_buy_fill(book, 20.0)
    decision = RiskManager(settings).evaluate(_proposal(amount=20.0), book, fill, ExposureSnapshot(bankroll=1000))
    assert decision.allowed is False
    assert decision.reason == "max_order_usd"


def test_risk_rejects_low_edge():
    settings = load_settings()
    book = _book()
    fill = simulate_buy_fill(book, 5.0)
    decision = RiskManager(settings).evaluate(_proposal(model_probability=0.51), book, fill, ExposureSnapshot(bankroll=1000))
    assert decision.allowed is False
    assert decision.reason == "min_edge"

