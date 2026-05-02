from hermes_polymarket.crypto.repricing import BboSnapshot, compute_repricing_lag


def test_repricing_lag_detected():
    updates = [
        BboSnapshot("token", 0.49, 0.51, 0.02, 1000),
        BboSnapshot("token", 0.48, 0.54, 0.06, 1300),
    ]

    assert compute_repricing_lag(external_move_ts_ms=1000, bbo_updates=updates, min_change_cents=2) == 300


def test_repricing_lag_missing_when_bbo_does_not_move_enough():
    updates = [
        BboSnapshot("token", 0.49, 0.51, 0.02, 1000),
        BboSnapshot("token", 0.49, 0.515, 0.025, 1300),
    ]

    assert compute_repricing_lag(external_move_ts_ms=1000, bbo_updates=updates, min_change_cents=2) is None
