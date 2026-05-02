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

    assert hits[0.03] >= 1
    assert hits[0.08] >= 1
