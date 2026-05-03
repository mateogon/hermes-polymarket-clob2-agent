from hermes_polymarket.crypto.strike_fair_value import fair_value_above_strike


def test_above_strike_probability_above_half_when_current_above():
    fv = fair_value_above_strike(current_price=79000, strike_price=78000, seconds_to_expiry=900)

    assert fv.probability_yes > 0.5


def test_above_strike_probability_below_half_when_current_below():
    fv = fair_value_above_strike(current_price=77000, strike_price=78000, seconds_to_expiry=900)

    assert fv.probability_yes < 0.5
