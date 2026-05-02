from hermes_polymarket.signals.crypto_latency_detector import detect_external_move
from hermes_polymarket.signals.source_consensus import ConsensusPrice


def consensus(price: float):
    return ConsensusPrice("btcusdt", price, ("binance", "coinbase"), 0.0, ())


def test_external_move_detected():
    event = detect_external_move(symbol="btcusdt", previous=consensus(100), current=consensus(101), min_move_pct=0.5, detected_ts_ms=1200)
    assert event is not None
    assert event.external_move_pct == 1.0
    assert event.symbol == "btcusdt"


def test_external_move_ignored_below_threshold():
    assert detect_external_move(symbol="btcusdt", previous=consensus(100), current=consensus(100.01), min_move_pct=0.5, detected_ts_ms=1200) is None


def test_external_move_ignored_bad_reference():
    assert detect_external_move(symbol="btcusdt", previous=consensus(0), current=consensus(100), min_move_pct=0.5, detected_ts_ms=1200) is None
