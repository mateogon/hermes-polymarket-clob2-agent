import httpx

from hermes_polymarket.data_sources.base import EventType
from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi, parse_wallet_trade
from hermes_polymarket.data_sources.polymarket_rtds import normalize_rtds_message


def test_parse_wallet_trade_from_data_api_shape():
    trade = parse_wallet_trade(
        {
            "proxyWallet": "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
            "side": "BUY",
            "asset": "123",
            "conditionId": "0x" + "a" * 64,
            "size": 10,
            "price": 0.42,
            "timestamp": 1710000000,
            "slug": "market-slug",
            "outcome": "Yes",
            "title": "Question?",
            "transactionHash": "0xabc",
        }
    )
    assert trade is not None
    assert trade.wallet.startswith("0x55")
    assert trade.notional_usd == 4.2
    assert trade.side == "BUY"


def test_data_api_client_sends_wallet_filters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["user"] == "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"
        assert request.url.params["side"] == "BUY"
        assert request.url.params["filterType"] == "CASH"
        return httpx.Response(
            200,
            json=[
                {
                    "proxyWallet": "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3",
                    "side": "BUY",
                    "asset": "123",
                    "conditionId": "0x" + "a" * 64,
                    "size": 10,
                    "price": 0.42,
                    "timestamp": 1710000000,
                    "slug": "market-slug",
                    "outcome": "Yes",
                    "transactionHash": "0xabc",
                }
            ],
        )

    client = PolymarketDataApi(httpx.Client(transport=httpx.MockTransport(handler)))
    trades = client.get_trades_for_wallet("0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3", side="buy", min_cash=100)
    assert len(trades) == 1
    assert trades[0].asset_id == "123"
    client.close()


def test_normalize_rtds_crypto_message():
    event = normalize_rtds_message(
        {"topic": "crypto_prices", "payload": {"symbol": "BTCUSDT", "price": "100", "timestamp": 1234}},
        received_ts_ms=1300,
    )
    assert event is not None
    assert event.event_type == EventType.RTDS_CRYPTO_PRICE
    assert event.key == "btcusdt"
    assert event.latency_ms == 66
