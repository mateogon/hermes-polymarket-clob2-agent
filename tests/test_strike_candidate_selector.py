from hermes_polymarket.crypto.strike_candidate_selector import StrikeRotationConfig, score_strike_candidate
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel


def _book(token_id: str, *, bid: float, ask: float, size: float = 100.0) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=(OrderBookLevel(bid, size),),
        asks=(OrderBookLevel(ask, size),),
    )


def _candidate(strike: float = 78_000.0) -> dict:
    return {
        "slug": "bitcoin-above-78k-on-may-3",
        "condition_id": "condition",
        "symbol": "btcusdt",
        "market_type": "above_strike",
        "score": 0.88,
        "strike_price": strike,
        "end_date": "2027-05-03T16:00:00Z",
        "yes_token_id": "yes",
        "no_token_id": "no",
    }


def test_selector_rejects_extreme_ask():
    scored = score_strike_candidate(
        _candidate(),
        current_price=78_500,
        yes_book=_book("yes", bid=0.982, ask=0.984, size=1000),
        no_book=_book("no", bid=0.016, ask=0.018, size=1000),
    )

    assert scored.recommended is False
    assert "extreme_price" in scored.reject_reasons


def test_selector_prefers_near_atm_non_extreme_candidate():
    scored = score_strike_candidate(
        _candidate(),
        current_price=78_500,
        yes_book=_book("yes", bid=0.54, ask=0.55, size=1000),
        no_book=_book("no", bid=0.44, ask=0.45, size=1000),
    )

    assert scored.recommended is True
    assert scored.score >= 0.75
    assert "near_atm" in scored.reasons
