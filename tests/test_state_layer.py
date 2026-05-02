from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.state.crypto_price_state import CryptoPriceState
from hermes_polymarket.state.orderbook_state import OrderBookState
from hermes_polymarket.state.source_state import SourceState


def event(event_type, key, payload):
    return DataEvent("src", event_type, 1000, 1100, key, payload)


def test_orderbook_state_replaces_and_applies_price_change_remove():
    state = OrderBookState()
    state.apply(
        event(
            EventType.POLY_BOOK,
            "asset-1",
            {
                "asset_id": "asset-1",
                "market": "0xabc",
                "bids": [{"price": "0.49", "size": "10"}],
                "asks": [{"price": "0.51", "size": "20"}],
            },
        )
    )
    assert state.by_token["asset-1"].best_bid == 0.49
    assert state.by_token["asset-1"].best_ask == 0.51

    state.apply(event(EventType.POLY_PRICE_CHANGE, "asset-1", {"asset_id": "asset-1", "market": "0xabc", "side": "BUY", "price": "0.49", "size": "0"}))
    assert state.by_token["asset-1"].best_bid is None


def test_orderbook_state_updates_bbo_and_marks_resolved_inactive():
    state = OrderBookState()
    state.apply(event(EventType.POLY_BEST_BID_ASK, "asset-1", {"asset_id": "asset-1", "market": "0xabc", "best_bid": "0.48", "best_ask": "0.52"}))
    assert round(state.by_token["asset-1"].spread, 2) == 0.04

    state.apply(event(EventType.POLY_MARKET_RESOLVED, "0xabc", {"market": "0xabc"}))
    assert state.by_token["asset-1"].active is False


def test_crypto_price_state_tracks_latest_prices():
    state = CryptoPriceState()
    state.apply(DataEvent("binance", EventType.BINANCE_BOOK_TICKER, None, 1000, "btcusdt", {"best_bid": 99, "best_ask": 101}))
    assert state.get("binance", "BTCUSDT").price == 100


def test_source_state_counts_messages_errors_and_drops():
    state = SourceState()
    status = state.apply(DataEvent("poly", EventType.POLY_BOOK, None, 1000, "asset", {}), dropped_events=2)
    assert status.messages_seen == 1
    assert status.dropped_events == 2
    assert status.status == "ok"

    status = state.apply(DataEvent("poly", EventType.SOURCE_HEALTH, None, 1100, "poly", {"ok": False}), dropped_events=1)
    assert status.messages_seen == 2
    assert status.errors_seen == 1
    assert status.dropped_events == 3
    assert status.status == "error"
