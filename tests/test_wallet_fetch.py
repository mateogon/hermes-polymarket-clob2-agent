import httpx

from hermes_polymarket.backtest.wallet_fetch import fetch_and_persist_wallet_trades_paginated, fetch_wallet_trades_paginated
from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi
from hermes_polymarket.storage.db import Database


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def _row(i: int):
    return {
        "proxyWallet": WALLET,
        "side": "BUY",
        "asset": f"asset-{i}",
        "conditionId": "condition",
        "size": 10,
        "price": 0.42,
        "timestamp": 1710000000 + i,
        "slug": "market-slug",
        "outcome": "Yes",
        "title": "Question?",
        "transactionHash": f"0x{i}",
    }


def test_paginated_fetch_uses_offsets_and_limit_total():
    seen_offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        seen_offsets.append(offset)
        rows = [_row(offset + i) for i in range(limit)]
        return httpx.Response(200, json=rows)

    client = PolymarketDataApi(httpx.Client(transport=httpx.MockTransport(handler)))
    trades = fetch_wallet_trades_paginated(client, wallet=WALLET, page_size=2, max_pages=10, limit_total=5)
    assert len(trades) == 5
    assert seen_offsets == [0, 2, 4]
    client.close()


def test_paginated_fetch_persists_page_counts(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        rows = [_row(offset + i) for i in range(limit)]
        return httpx.Response(200, json=rows)

    db = Database(tmp_path / "wallet_fetch.sqlite3")
    db.init_schema(1000)
    client = PolymarketDataApi(httpx.Client(transport=httpx.MockTransport(handler)))
    result = fetch_and_persist_wallet_trades_paginated(db, client, wallet=WALLET, page_size=2, max_pages=2, limit_total=3)
    assert result.fetched_total == 3
    assert result.inserted_total == 3
    assert [page.offset for page in result.pages] == [0, 2]
    client.close()
    db.close()
