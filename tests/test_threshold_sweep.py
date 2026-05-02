from hermes_polymarket.crypto.threshold_sweep import count_threshold_hits


def test_threshold_sweep_counts_hits():
    rows = [
        (1000, 100.0),
        (2000, 100.02),
        (3000, 100.10),
    ]

    result = count_threshold_hits(
        symbol="btcusdt",
        prices=rows,
        thresholds_pct=[0.03, 0.08],
        lookback_ms=3000,
    )
    hits = {row.threshold_pct: row.hits for row in result}
    max_moves = {row.threshold_pct: row.max_move_pct for row in result}

    assert hits[0.03] >= 1
    assert hits[0.08] >= 1
    assert max_moves[0.08] > 0.0


def test_threshold_sweep_respects_cooldown():
    rows = [
        (1000, 100.0),
        (1100, 100.1),
        (1200, 100.2),
    ]

    result = count_threshold_hits(
        symbol="btcusdt",
        prices=rows,
        thresholds_pct=[0.03],
        lookback_ms=1000,
        cooldown_ms=1000,
    )

    assert result[0].hits == 1
