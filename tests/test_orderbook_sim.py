import pytest

from hermes_polymarket.polymarket.orderbook import parse_orderbook, simulate_buy_fill, simulate_sell_fill


def book():
    return parse_orderbook(
        "t",
        {
            "bids": [{"price": "0.48", "size": "100"}, {"price": "0.47", "size": "200"}],
            "asks": [{"price": "0.50", "size": "10"}, {"price": "0.52", "size": "100"}],
        },
    )


def test_single_level_buy_fill():
    fill = simulate_buy_fill(book(), 5.0)
    assert fill.filled is True
    assert fill.avg_price == pytest.approx(0.50)
    assert fill.total_shares == pytest.approx(10.0)


def test_multi_level_buy_fill():
    fill = simulate_buy_fill(book(), 10.2)
    assert fill.filled is True
    assert fill.levels_filled == 2
    assert fill.total_cost == pytest.approx(10.2)
    assert fill.total_shares > 19


def test_thin_book_fok_rejection():
    fill = simulate_buy_fill(book(), 1000.0, order_type="fok")
    assert fill.filled is False
    assert fill.status == "liquidity_rejected"


def test_fak_partial_fill():
    fill = simulate_buy_fill(book(), 1000.0, order_type="fak")
    assert fill.is_partial is True
    assert fill.total_shares == pytest.approx(110.0)


def test_empty_book_rejection():
    empty = parse_orderbook("t", {"bids": [], "asks": []})
    assert simulate_buy_fill(empty, 5.0).status == "empty_book"
    assert simulate_sell_fill(empty, 5.0).status == "empty_book"


def test_sell_walks_bid_side():
    fill = simulate_sell_fill(book(), 150.0, order_type="fak")
    assert fill.levels_filled == 2
    assert fill.avg_price < 0.48

