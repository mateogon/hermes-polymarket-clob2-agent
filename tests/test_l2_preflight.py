from hermes_polymarket.crypto.l2_preflight import _book_event
from hermes_polymarket.polymarket.types import OrderBook, OrderBookLevel
from hermes_polymarket.state.orderbook_state import OrderBookState


def test_book_event_can_seed_orderbook_state():
    book = OrderBook(
        "token",
        bids=(OrderBookLevel(0.49, 100),),
        asks=(OrderBookLevel(0.51, 100),),
    )

    event = _book_event(book, received_ts_ms=1000)
    state = OrderBookState()
    state.apply(event)

    assert state.by_token["token"].best_bid == 0.49
    assert state.by_token["token"].best_ask == 0.51
