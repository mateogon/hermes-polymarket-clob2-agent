import json

from hermes_polymarket import cli
from hermes_polymarket.data_sources.binance_historical import BinanceCandle
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.research.candidate_batch import CandidateBatchConfig, run_research_candidate_batch
from hermes_polymarket.research.data_cache import ResearchDataCache


def _market():
    return {
        "active": True,
        "closed": False,
        "question": "Will Bitcoin hit $110 by December 31, 2026?",
        "slug": "bitcoin-hit-110",
        "conditionId": "condition",
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "endDate": "2026-12-31T00:00:00Z",
    }


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
    return WalletTrade("0xabc", "BUY", "condition", "yes-token", "Yes", price, 100, ts, "bitcoin-hit-110", "t", f"tx-{ts}", raw)


class FakeGamma:
    def list_events(self, **_):
        return []

    def list_markets(self, **_):
        return [_market()]

    def markets_by_slug(self, slug):
        assert slug == "bitcoin-hit-110"
        return [_market()]

    def close(self):
        pass


class FakeDataApi:
    def get_trades(self, **_):
        return [_trade(100, 0.01), _trade(220, 0.03)]

    def close(self):
        pass


class FakeBinance:
    def get_klines_paginated(self, **_):
        return [
            BinanceCandle(90_000, 149_999, 100, 101, 99, 100, 1),
            BinanceCandle(150_000, 209_999, 100, 102, 99, 101, 1),
            BinanceCandle(210_000, 269_999, 101, 102, 100, 101, 1),
        ]

    def close(self):
        pass


def test_research_candidate_batch_runs_cache_and_sweep(tmp_path):
    payload = run_research_candidate_batch(
        config=CandidateBatchConfig(
            symbols=("btcusdt",),
            families=("target_hit",),
            candidate_limit=1,
            min_trades=1,
            vol_mode="fixed",
            vol_grid=(2.0,),
            edge_grid=(0.0,),
            hold_grid=(60,),
            cost_cents_grid=(0.0,),
            output_dir=tmp_path / "out",
        ),
        cache=ResearchDataCache(tmp_path / "cache"),
        gamma=FakeGamma(),
        data_api=FakeDataApi(),
        binance=FakeBinance(),
    )

    assert payload["candidates_found"] == 1
    assert payload["trades_cached"] == 2
    assert payload["candles_cached"] == 3
    assert payload["sweeps_run"] == 1
    assert payload["candidate_reports"][0]["top"]["net_pnl"] > 0
    assert (tmp_path / "out" / "summary.json").exists()


def test_research_candidate_batch_cli(monkeypatch, tmp_path, capsys):
    def fake_run(*, config):
        assert config.symbols == ("btcusdt",)
        assert config.families == ("target_hit",)
        return {"mode": "research_candidate_batch", "data_quality": "research_cache_public_historical", "cost_survivors": 0}

    monkeypatch.setattr("hermes_polymarket.research.candidate_batch.run_research_candidate_batch", fake_run)

    assert cli.main(["research", "candidate-batch", "--symbols", "btcusdt", "--families", "target_hit", "--output-dir", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"] == "default"
    assert payload["mode"] == "research_candidate_batch"
