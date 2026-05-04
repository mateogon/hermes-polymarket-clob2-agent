from hermes_polymarket.data_sources.binance_historical import _parse_kline


def test_parse_binance_kline():
    candle = _parse_kline([1000, "1.0", "2.0", "0.5", "1.5", "42", 59999])

    assert candle.open_ts_ms == 1000
    assert candle.close_ts_ms == 59999
    assert candle.close == 1.5
    assert candle.volume == 42.0
