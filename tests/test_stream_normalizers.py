from hermes_polymarket.data_sources.base import EventType
from hermes_polymarket.data_sources.binance_stream import binance_combined_stream_url, normalize_binance_message
from hermes_polymarket.data_sources.coinbase_stream import coinbase_subscriptions, normalize_coinbase_message
from hermes_polymarket.data_sources.kraken_stream import kraken_ticker_subscription, normalize_kraken_message
from hermes_polymarket.data_sources.polymarket_market_ws import market_subscription, normalize_market_ws_payload


def test_polymarket_market_ws_normalizes_supported_events():
    sub = market_subscription(["1", "2"])
    assert sub["custom_feature_enabled"] is True
    assert sub["assets_ids"] == ["1", "2"]

    events = normalize_market_ws_payload(
        [
            {"event_type": "best_bid_ask", "asset_id": "1", "bid": "0.49", "ask": "0.51", "timestamp": "1000"},
            {"event_type": "ignored"},
        ],
        received_ts_ms=1100,
    )
    assert len(events) == 1
    assert events[0].event_type == EventType.POLY_BEST_BID_ASK
    assert events[0].key == "1"
    assert events[0].latency_ms == 100


def test_polymarket_market_ws_ignores_pong():
    assert normalize_market_ws_payload("PONG", received_ts_ms=1000) == []


def test_polymarket_price_change_is_exploded_by_asset_id_and_removed_flag():
    events = normalize_market_ws_payload(
        {
            "event_type": "price_change",
            "market": "0xabc",
            "timestamp": "1757908892351",
            "price_changes": [
                {"asset_id": "asset-1", "price": "0.5", "size": "200", "side": "BUY"},
                {"asset_id": "asset-2", "price": "0.5", "size": "0", "side": "SELL"},
            ],
        },
        received_ts_ms=1757908892400,
    )
    assert [event.key for event in events] == ["asset-1", "asset-2"]
    assert all(event.event_type == EventType.POLY_PRICE_CHANGE for event in events)
    assert events[0].payload["market"] == "0xabc"
    assert events[0].payload["removed"] is False
    assert events[1].payload["removed"] is True


def test_polymarket_market_ws_normalizes_tick_size_change_and_new_market():
    events = normalize_market_ws_payload(
        [
            {"event_type": "tick_size_change", "asset_id": "asset-1", "market": "0xabc", "new_tick_size": "0.001"},
            {"event_type": "new_market", "condition_id": "0xdef", "clob_token_ids": ["1", "2"]},
        ],
        received_ts_ms=1000,
    )
    assert events[0].event_type == EventType.POLY_TICK_SIZE_CHANGE
    assert events[0].key == "asset-1"
    assert events[1].event_type == EventType.POLY_NEW_MARKET
    assert events[1].key == "0xdef"


def test_binance_normalizes_trade_book_and_kline():
    assert "btcusdt@aggTrade" in binance_combined_stream_url(["BTCUSDT"])

    trade = normalize_binance_message({"e": "aggTrade", "s": "BTCUSDT", "p": "100.5", "q": "2", "T": 1000}, 1100)
    assert trade.event_type == EventType.BINANCE_TRADE
    assert trade.payload["price"] == 100.5

    book = normalize_binance_message({"u": 1, "s": "BTCUSDT", "b": "100", "B": "3", "a": "101", "A": "4"}, 1100)
    assert book.event_type == EventType.BINANCE_BOOK_TICKER
    assert book.payload["best_ask"] == 101.0

    kline = normalize_binance_message(
        {
            "e": "kline",
            "E": 1200,
            "k": {"s": "BTCUSDT", "i": "1s", "o": "1", "h": "2", "l": "1", "c": "1.5", "v": "10", "x": False, "t": 1, "T": 2},
        },
        1300,
    )
    assert kline.event_type == EventType.BINANCE_KLINE
    assert kline.payload["close"] == 1.5


def test_coinbase_normalizes_ticker_events():
    messages = coinbase_subscriptions(["BTC-USD"])
    assert messages[1]["channel"] == "ticker"
    events = normalize_coinbase_message(
        {"channel": "ticker", "events": [{"tickers": [{"product_id": "BTC-USD", "price": "100"}]}]},
        received_ts_ms=2000,
    )
    assert len(events) == 1
    assert events[0].event_type == EventType.COINBASE_TICKER
    assert events[0].payload["price"] == 100.0


def test_kraken_normalizes_ticker_events():
    assert kraken_ticker_subscription(["BTC/USD"])["params"]["channel"] == "ticker"
    events = normalize_kraken_message(
        {"channel": "ticker", "data": [{"symbol": "BTC/USD", "bid": "100", "ask": "101", "last": "100.5"}]},
        received_ts_ms=2000,
    )
    assert len(events) == 1
    assert events[0].event_type == EventType.KRAKEN_TICKER
    assert events[0].payload["last"] == 100.5
