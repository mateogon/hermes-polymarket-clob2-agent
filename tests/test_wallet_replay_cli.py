from dataclasses import replace

import hermes_polymarket.cli as cli
from hermes_polymarket.backtest.wallet_replay_storage import insert_wallet_trades
from hermes_polymarket.config import load_settings
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.storage.db import Database


WALLET = "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"


def _trade(side="BUY", ts=100, price=0.5, tx="tx"):
    return WalletTrade(
        wallet=WALLET,
        side=side,
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        price=price,
        size=100,
        timestamp=ts,
        slug="btc-up",
        title="BTC up?",
        tx_hash=f"{tx}-{side}-{ts}",
        raw={
            "proxyWallet": WALLET,
            "side": side,
            "conditionId": "c",
            "asset": "a",
            "outcome": "Yes",
            "price": price,
            "size": 100,
            "timestamp": ts,
            "slug": "btc-up",
            "title": "BTC up?",
            "transactionHash": f"{tx}-{side}-{ts}",
        },
    )


def _patch_settings(monkeypatch, tmp_path):
    settings = replace(load_settings(), database_path=tmp_path / "cli.sqlite3")
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setenv("HERMES_ARTIFACTS_DIR", str(tmp_path / "artifacts" / "runs"))
    return settings


def test_wallet_replay_without_fetched_trades_returns_clear_error(monkeypatch, tmp_path, capsys):
    _patch_settings(monkeypatch, tmp_path)
    assert cli.main(["wallet-flow", "replay", "--wallet", "coinman2", "--delay", "0,2", "--mode", "historical-approx"]) == 2
    assert "Run wallet-flow fetch first" in capsys.readouterr().out


def test_wallet_replay_cli_uses_persisted_trades_and_writes_learning(monkeypatch, tmp_path):
    settings = _patch_settings(monkeypatch, tmp_path)
    db = Database(settings.database_path)
    db.init_schema(1000)
    insert_wallet_trades(
        db,
        [
            _trade("BUY", 100, 0.5, "a"),
            _trade("SELL", 150, 0.7, "b"),
            _trade("BUY", 200, 0.5, "c"),
            _trade("SELL", 250, 0.7, "d"),
            _trade("BUY", 300, 0.5, "e"),
            _trade("SELL", 350, 0.7, "f"),
        ],
    )
    db.close()

    assert cli.main(["wallet-flow", "replay", "--wallet", "coinman2", "--delay", "0", "--mode", "historical-approx", "--export-csv", "--quality-warnings"]) == 0

    db = Database(settings.database_path)
    db.init_schema(1000)
    assert db.conn.execute("SELECT COUNT(*) FROM wallet_replay_trades").fetchone()[0] == 3
    assert db.conn.execute("SELECT COUNT(*) FROM strategy_experiments").fetchone()[0] == 1
    memory = db.conn.execute("SELECT * FROM agent_memories").fetchone()
    assert memory["status"] == "candidate_rule"
    assert memory["active_in_paper"] == 0
    assert memory["active_in_live"] == 0
    artifact_files = list((tmp_path / "artifacts" / "runs").rglob("*"))
    assert any(path.name == "manifest.json" for path in artifact_files)
    assert any(path.name == "replay_trades.csv" for path in artifact_files)
    db.close()


def test_wallet_fetch_persists_and_dedupes(monkeypatch, tmp_path, capsys):
    settings = _patch_settings(monkeypatch, tmp_path)

    class FakeDataApi:
        def get_trades_for_wallet(self, wallet, *, limit=100, min_cash=None, **_):
            assert wallet == WALLET
            assert limit == 2
            return [_trade("BUY", 100, 0.5), _trade("BUY", 100, 0.5)]

        def close(self):
            pass

    monkeypatch.setattr("hermes_polymarket.data_sources.polymarket_data_api.PolymarketDataApi", FakeDataApi)
    assert cli.main(["wallet-flow", "fetch", "--wallet", "coinman2", "--page-size", "2", "--max-pages", "1", "--limit-total", "2", "--side", "buy"]) == 0
    output = capsys.readouterr().out
    assert '"inserted_count": 1' in output
    assert '"duplicate_count": 1' in output

    db = Database(settings.database_path)
    db.init_schema(1000)
    assert db.conn.execute("SELECT COUNT(*) FROM wallet_observed_trades").fetchone()[0] == 1
    db.close()


def test_wallet_score_persists_and_leaderboard_reads_scores(monkeypatch, tmp_path, capsys):
    settings = _patch_settings(monkeypatch, tmp_path)
    db = Database(settings.database_path)
    db.init_schema(1000)
    insert_wallet_trades(db, [_trade("BUY", 100, 0.5), _trade("SELL", 200, 0.7)])
    db.close()

    assert cli.main(["wallet-flow", "replay", "--wallet", "coinman2", "--delay", "0"]) == 0
    assert cli.main(["wallet-flow", "score", "--wallet", "coinman2"]) == 0
    score_output = capsys.readouterr().out
    assert "small_sample" in score_output
    assert cli.main(["wallet-flow", "leaderboard"]) == 0
    assert WALLET in capsys.readouterr().out
