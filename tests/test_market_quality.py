from hermes_polymarket.crypto.market_quality import evaluate_market_quality
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel


def test_market_quality_rejects_extreme_low_ask():
    book = OrderBook(
        token_id="t",
        bids=(),
        asks=(OrderBookLevel(0.001, 100),),
    )

    decision = evaluate_market_quality(book)

    assert decision.allowed is False
    assert decision.reason in {"no_best_bid", "extreme_low_ask"}


def test_market_quality_allows_healthy_book():
    book = OrderBook(
        token_id="t",
        bids=(OrderBookLevel(0.49, 100),),
        asks=(OrderBookLevel(0.51, 100),),
    )

    decision = evaluate_market_quality(book)

    assert decision.allowed is True


def test_market_quality_rejects_thin_depth():
    book = OrderBook(
        token_id="t",
        bids=(OrderBookLevel(0.49, 100),),
        asks=(OrderBookLevel(0.51, 1),),
    )

    decision = evaluate_market_quality(book)

    assert decision.allowed is False
    assert decision.reason == "thin_depth_2pct"
