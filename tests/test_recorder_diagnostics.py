from hermes_polymarket.crypto.recorder_diagnostics import RecorderDiagnostics


def test_recorder_diagnostics_counts_sources():
    diagnostics = RecorderDiagnostics()
    diagnostics.seen_event("binance")
    diagnostics.seen_event("binance")
    diagnostics.seen_reading("coinbase")
    diagnostics.seen_consensus("btcusdt")

    out = diagnostics.to_dict()

    assert out["events_seen_by_source"]["binance"] == 2
    assert out["readings_by_source"]["coinbase"] == 1
    assert out["consensus_ticks_by_symbol"]["btcusdt"] == 1


def test_recorder_diagnostics_counts_threshold_hits():
    diagnostics = RecorderDiagnostics()
    diagnostics.threshold_hit("btcusdt", 0.03)
    diagnostics.threshold_hit("btcusdt", 0.03)

    assert diagnostics.to_dict()["threshold_hits_by_symbol"]["btcusdt"]["0.03"] == 2
