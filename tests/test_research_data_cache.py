import json

from hermes_polymarket.data_sources.binance_historical import BinanceCandle
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.research.data_cache import ResearchDataCache


def test_research_cache_writes_and_loads_trades_and_candles(tmp_path):
    cache = ResearchDataCache(tmp_path)
    trade = WalletTrade(
        wallet="0xabc",
        side="BUY",
        condition_id="c",
        asset_id="token",
        outcome="Yes",
        price=0.42,
        size=10,
        timestamp=100,
        slug="s",
        title="t",
        tx_hash="tx",
        raw={
            "proxyWallet": "0xabc",
            "side": "BUY",
            "conditionId": "c",
            "asset": "token",
            "outcome": "Yes",
            "price": 0.42,
            "size": 10,
            "timestamp": 100,
        },
    )
    trade_manifest = cache.write_polymarket_trades(condition_id="c", trades=[trade], params={"condition_id": "c"})

    assert trade_manifest["rows"] == 1
    assert cache.load_polymarket_trades(condition_id="c")[0].price == 0.42

    candle = BinanceCandle(open_ts_ms=1, close_ts_ms=60_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=42.0)
    candle_manifest = cache.write_binance_klines(
        symbol="btcusdt",
        interval="1m",
        start_ts_ms=1,
        end_ts_ms=60_000,
        candles=[candle],
        params={"symbol": "btcusdt"},
    )

    assert candle_manifest["data_quality"] == "research_cache_public_historical"
    assert cache.load_binance_klines(symbol="btcusdt", interval="1m", start_ts_ms=1, end_ts_ms=60_000)[0]["close"] == 1.5
    assert cache.status()["groups"]["polymarket_trades"]["files"] == 1


def test_research_cache_writes_gamma_market(tmp_path):
    cache = ResearchDataCache(tmp_path)

    manifest = cache.write_gamma_market(slug="market slug", markets=[{"slug": "market slug"}], params={"slug": "market slug"})

    assert manifest["rows"] == 1
    payload = json.loads((tmp_path / "gamma_markets" / "market_slug.json").read_text())
    assert payload["markets"][0]["slug"] == "market slug"
