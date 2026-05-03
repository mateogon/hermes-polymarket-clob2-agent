from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target


def test_parse_hit_k_target():
    info = parse_multi_strike_target("will-bitcoin-hit-150k-by-june-30-2026", current_price=100000)

    assert info is not None
    assert info.market_type == "multi_strike_event"
    assert info.target_price == 150000
    assert info.target_direction == "above"


def test_parse_reach_pt_decimal_target():
    info = parse_multi_strike_target("will-xrp-reach-3pt80-by-december-31-2026", current_price=2.5)

    assert info is not None
    assert info.target_price == 3.8
    assert info.target_direction == "above"


def test_barrier_probability_decreases_for_farther_target():
    near = fair_value_target_hit(current_price=100.0, target_price=110.0, seconds_to_expiry=31_536_000)
    far = fair_value_target_hit(current_price=100.0, target_price=200.0, seconds_to_expiry=31_536_000)

    assert near.probability_yes > far.probability_yes
    assert near.reason == "barrier_touch_diffusion_approx"


def test_barrier_probability_high_if_already_crossed():
    fv = fair_value_target_hit(current_price=110.0, target_price=110.0, seconds_to_expiry=1000)

    assert fv.probability_yes == 0.99
    assert fv.reason == "target_already_crossed"
