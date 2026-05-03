from hermes_polymarket.crypto.strike_market import parse_strike_market


def test_parse_above_k_slug():
    info = parse_strike_market("bitcoin-above-78k-on-may-3")

    assert info is not None
    assert info.market_type == "above_strike"
    assert info.comparator == "above"
    assert info.strike_price == 78000


def test_parse_below_dollar_question():
    info = parse_strike_market("Will Bitcoin be below $75,000?")

    assert info is not None
    assert info.market_type == "below_strike"
    assert info.strike_price == 75000
