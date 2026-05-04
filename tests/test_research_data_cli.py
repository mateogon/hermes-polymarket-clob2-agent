import json

from hermes_polymarket import cli
from hermes_polymarket.data_sources.binance_historical import BinanceCandle


class FakeBinanceHistoricalClient:
    def get_klines_paginated(self, **_):
        return [BinanceCandle(open_ts_ms=1, close_ts_ms=60_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=42.0)]

    def close(self):
        pass


class FakeGammaClient:
    def markets_by_slug(self, slug):
        return [{"slug": slug, "conditionId": "c"}]

    def close(self):
        pass


def test_research_data_status_uses_cache_dir(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))
    monkeypatch.setenv("HERMES_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))

    assert cli.main(["research", "data", "status"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["environment"] == "research"
    assert payload["mode"] == "research_data_cache_status"
    assert payload["root"] == str(tmp_path / "cache")


def test_research_data_fetch_binance_klines(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))
    monkeypatch.setenv("HERMES_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("hermes_polymarket.data_sources.binance_historical.BinanceHistoricalClient", FakeBinanceHistoricalClient)

    assert (
        cli.main(
            [
                "research",
                "data",
                "fetch",
                "--kind",
                "binance-klines",
                "--symbol",
                "btcusdt",
                "--start-ts-ms",
                "1",
                "--end-ts-ms",
                "60000",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"]["rows"] == 1
    assert (tmp_path / "cache" / "binance_klines" / "btcusdt_1m_1_60000.jsonl").exists()


def test_research_data_fetch_gamma_market(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HERMES_ENV", "research")
    monkeypatch.setenv("HERMES_DATABASE_PATH", str(tmp_path / "research.sqlite3"))
    monkeypatch.setenv("HERMES_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("hermes_polymarket.polymarket.gamma_client.GammaClient", FakeGammaClient)

    assert cli.main(["research", "data", "fetch", "--kind", "gamma-market", "--slug", "some-market"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"]["rows"] == 1
    assert (tmp_path / "cache" / "gamma_markets" / "some-market.json").exists()
