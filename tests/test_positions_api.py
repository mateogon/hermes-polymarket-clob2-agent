import httpx

from hermes_polymarket.data_sources.polymarket_positions_api import PolymarketPositionsApi, parse_closed_position, parse_current_position


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def _closed_row():
    return {
        "proxyWallet": WALLET,
        "asset": "asset",
        "conditionId": "0x" + "a" * 64,
        "avgPrice": 0.4,
        "totalBought": 100,
        "realizedPnl": 12.5,
        "curPrice": 1,
        "timestamp": 123,
        "title": "title",
        "slug": "slug",
        "eventSlug": "event",
        "outcome": "Yes",
        "outcomeIndex": 0,
        "oppositeOutcome": "No",
        "oppositeAsset": "other",
        "endDate": "2026-01-01",
    }


def _current_row():
    row = _closed_row()
    row.update(
        {
            "size": 10,
            "initialValue": 4,
            "currentValue": 5,
            "cashPnl": 1,
            "percentPnl": 25,
            "redeemable": False,
            "mergeable": False,
            "negativeRisk": False,
        }
    )
    return row


def test_parse_closed_position():
    pos = parse_closed_position(_closed_row())
    assert pos is not None
    assert pos.realized_pnl == 12.5
    assert pos.asset_id == "asset"


def test_parse_current_position():
    pos = parse_current_position(_current_row())
    assert pos is not None
    assert pos.size == 10
    assert pos.current_value == 5


def test_positions_api_sends_expected_params():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["user"] == WALLET
        assert request.url.params["limit"] == "7"
        assert request.url.params["offset"] == "14"
        assert request.url.params["sortBy"] == "TIMESTAMP"
        return httpx.Response(200, json=[_closed_row()])

    client = PolymarketPositionsApi(httpx.Client(transport=httpx.MockTransport(handler)))
    rows = client.closed_positions(WALLET, limit=7, offset=14)
    assert len(rows) == 1
    client.close()
