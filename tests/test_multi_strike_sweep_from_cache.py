import json

from hermes_polymarket import cli
from hermes_polymarket.data_sources.binance_historical import BinanceCandle
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.research.data_cache import ResearchDataCache


def _trade(ts: int, price: float) -> WalletTrade:
    raw = {
        "proxyWallet": "0xabc",
        "side": "BUY",
        "conditionId": "condition",
        "asset": "yes-token",
        "outcome": "Yes",
        "price": price,
        "size": 100,
        "timestamp": ts,
    }
    return WalletTrade(
        wallet="0xabc",
        side="BUY",
        condition_id="condition",
        asset_id="yes-token",
        outcome="Yes",
        price=price,
        size=100,
        timestamp=ts,
        slug="bitcoin-hit-110",
        title="Will Bitcoin hit 110?",
        tx_hash=f"tx-{ts}",
        raw=raw,
    )


def test_multi_strike_sweep_from_cache_runs_without_network(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))
    cache = ResearchDataCache(tmp_path / "cache")
    cache.write_gamma_market(
        slug="bitcoin-hit-110",
        markets=[
            {
                "slug": "bitcoin-hit-110",
                "question": "Will Bitcoin hit $110 by December 31, 2026?",
                "conditionId": "condition",
                "clobTokenIds": json.dumps(["yes-token", "no-token"]),
                "endDate": "2026-12-31T00:00:00Z",
            }
        ],
        params={"slug": "bitcoin-hit-110"},
    )
    cache.write_polymarket_trades(condition_id="condition", trades=[_trade(100, 0.01), _trade(220, 0.03)], params={})
    candles = [
        BinanceCandle(open_ts_ms=90_000, close_ts_ms=149_999, open=100, high=101, low=99, close=100, volume=1),
        BinanceCandle(open_ts_ms=150_000, close_ts_ms=209_999, open=100, high=102, low=99, close=101, volume=1),
        BinanceCandle(open_ts_ms=210_000, close_ts_ms=269_999, open=101, high=102, low=100, close=101, volume=1),
    ]
    cache.write_binance_klines(symbol="btcusdt", interval="1m", start_ts_ms=90_000, end_ts_ms=300_000, candles=candles, params={})

    assert (
        cli.main(
            [
                "multi-strike",
                "sweep-from-cache",
                "--market-slugs",
                "bitcoin-hit-110",
                "--symbol",
                "btcusdt",
                "--edge-grid",
                "0.0",
                "--hold-grid",
                "60",
                "--cost-cents-grid",
                "0",
                "--vol-grid",
                "2.0",
                "--min-trades",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "multi_strike_sweep_from_cache"
    assert payload["markets"][0]["status"] == "ok"
    assert payload["top"][0]["simulated_trades"] == 1
    assert payload["top"][0]["net_pnl"] > 0


def test_multi_strike_sweep_from_cache_reports_missing_cache(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))

    assert cli.main(["multi-strike", "sweep-from-cache", "--market-slugs", "missing", "--symbol", "btcusdt"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["markets"][0]["status"] == "missing_gamma_market_cache"
    assert payload["rows"] == []
