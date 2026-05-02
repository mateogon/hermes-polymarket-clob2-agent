from hermes_polymarket.crypto.event_adapter import bbo_from_event, price_reading_from_event
from hermes_polymarket.data_sources.base import DataEvent, EventType


def test_price_reading_from_binance_book_ticker_midpoint():
    event = DataEvent(
        source="binance",
        event_type=EventType.BINANCE_BOOK_TICKER,
        event_ts_ms=None,
        received_ts_ms=1000,
        key="btcusdt",
        payload={"best_bid": 99.0, "best_ask": 101.0},
    )

    reading = price_reading_from_event(event)

    assert reading is not None
    assert reading.source == "binance"
    assert reading.symbol == "btcusdt"
    assert reading.price == 100.0


def test_price_reading_from_coinbase_normalizes_usd_product():
    event = DataEvent(
        source="coinbase",
        event_type=EventType.COINBASE_TICKER,
        event_ts_ms=None,
        received_ts_ms=1000,
        key="btc-usd",
        payload={"product_id": "BTC-USD", "price": 100.5},
    )

    reading = price_reading_from_event(event)

    assert reading is not None
    assert reading.source == "coinbase"
    assert reading.symbol == "btcusdt"
    assert reading.price == 100.5


def test_price_reading_from_rtds_prefers_value_field():
    event = DataEvent(
        source="polymarket_rtds",
        event_type=EventType.RTDS_CRYPTO_PRICE,
        event_ts_ms=1000,
        received_ts_ms=1001,
        key="btcusdt",
        payload={"value": 101.25, "price": 99.0},
    )

    reading = price_reading_from_event(event)

    assert reading is not None
    assert reading.source == "polymarket_rtds"
    assert reading.symbol == "btcusdt"
    assert reading.price == 101.25


def test_price_reading_from_kraken_normalizes_usd_pair():
    event = DataEvent(
        source="kraken",
        event_type=EventType.KRAKEN_TICKER,
        event_ts_ms=None,
        received_ts_ms=1000,
        key="btc/usd",
        payload={"last": 100.25},
    )

    reading = price_reading_from_event(event)

    assert reading is not None
    assert reading.source == "kraken"
    assert reading.symbol == "btcusdt"
    assert reading.price == 100.25


def test_bbo_from_polymarket_event():
    event = DataEvent(
        source="polymarket",
        event_type=EventType.POLY_BEST_BID_ASK,
        event_ts_ms=None,
        received_ts_ms=1000,
        key="token-1",
        payload={"best_bid": "0.49", "best_ask": "0.51"},
    )

    assert bbo_from_event(event) == ("token-1", {"best_bid": "0.49", "best_ask": "0.51"})
