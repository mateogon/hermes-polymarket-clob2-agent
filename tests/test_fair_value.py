from hermes_polymarket.crypto.fair_value import evaluate_fair_value_edge, fair_value_up


def test_fair_value_up_above_reference():
    assert fair_value_up(current_price=101, reference_price=100, seconds_to_expiry=300) > 0.5


def test_fair_value_up_below_reference():
    assert fair_value_up(current_price=99, reference_price=100, seconds_to_expiry=300) < 0.5


def test_fair_value_stronger_with_distance():
    near = fair_value_up(current_price=100.1, reference_price=100, seconds_to_expiry=300)
    far = fair_value_up(current_price=101, reference_price=100, seconds_to_expiry=300)
    assert far > near


def test_fair_value_stronger_near_expiry():
    long = fair_value_up(current_price=100.1, reference_price=100, seconds_to_expiry=900)
    short = fair_value_up(current_price=100.1, reference_price=100, seconds_to_expiry=60)
    assert short > long


def test_fair_value_rejects_low_edge():
    decision = evaluate_fair_value_edge(
        direction="up",
        current_price=100.01,
        reference_price=100,
        seconds_to_expiry=900,
        executable_price=0.60,
        min_edge=0.03,
    )
    assert decision.allowed is False
    assert decision.reason == "edge_below_min"
