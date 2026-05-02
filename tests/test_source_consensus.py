from hermes_polymarket.signals.source_consensus import PriceReading, consensus_price


def test_consensus_rejects_stale_sources():
    readings = [
        PriceReading("binance", "btcusdt", 100, 0),
        PriceReading("coinbase", "btcusdt", 100, 0),
    ]
    assert consensus_price(readings, now_ms=10_000, max_age_ms=1000) is None


def test_consensus_rejects_divergent_sources():
    readings = [
        PriceReading("binance", "btcusdt", 100, 1000),
        PriceReading("coinbase", "btcusdt", 110, 1000),
    ]
    assert consensus_price(readings, now_ms=1000, max_deviation_pct_allowed=0.25) is None


def test_consensus_accepts_fresh_close_sources():
    readings = [
        PriceReading("binance", "btcusdt", 100.00, 1000),
        PriceReading("coinbase", "btcusdt", 100.05, 1000),
    ]
    result = consensus_price(readings, now_ms=1100)
    assert result is not None
    assert result.symbol == "btcusdt"
    assert result.sources == ("binance", "coinbase")
