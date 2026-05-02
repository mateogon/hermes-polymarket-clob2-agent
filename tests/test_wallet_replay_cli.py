from dataclasses import replace

import hermes_polymarket.cli as cli
from hermes_polymarket.backtest.wallet_replay_storage import insert_wallet_trades
from hermes_polymarket.config import load_settings
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.data_sources.polymarket_positions_api import ClosedPosition, CurrentPosition
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.wallet_positions import insert_closed_positions, upsert_current_positions


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


def test_wallet_exit_coverage_cli_uses_persisted_trades(monkeypatch, tmp_path, capsys):
    settings = _patch_settings(monkeypatch, tmp_path)
    db = Database(settings.database_path)
    db.init_schema(1000)
    insert_wallet_trades(db, [_trade("BUY", 100, 0.5), _trade("SELL", 200, 0.7)])
    db.close()

    assert cli.main(["wallet-flow", "exit-coverage", "--wallet", "coinman2"]) == 0
    output = capsys.readouterr().out
    assert '"buy_assets_with_sell": 1' in output


def _current_position():
    return CurrentPosition(
        wallet=WALLET,
        asset_id="a",
        condition_id="c",
        size=10,
        avg_price=0.4,
        initial_value=4,
        current_value=5,
        cash_pnl=1,
        percent_pnl=25,
        total_bought=100,
        realized_pnl=0,
        cur_price=0.5,
        redeemable=False,
        mergeable=False,
        title="title",
        slug="slug",
        event_slug="event",
        outcome="Yes",
        outcome_index=0,
        opposite_outcome="No",
        opposite_asset="other",
        end_date="2026-01-01",
        negative_risk=False,
        raw={},
    )


def _closed_position():
    return ClosedPosition(
        wallet=WALLET,
        asset_id="a",
        condition_id="c",
        avg_price=0.4,
        total_bought=100,
        realized_pnl=12.5,
        cur_price=1,
        timestamp=123,
        title="title",
        slug="slug",
        event_slug="event",
        outcome="Yes",
        outcome_index=0,
        opposite_outcome="No",
        opposite_asset="other",
        end_date="2026-01-01",
        raw={},
    )


def test_wallet_positions_cli_report_and_current(monkeypatch, tmp_path, capsys):
    settings = _patch_settings(monkeypatch, tmp_path)
    db = Database(settings.database_path)
    db.init_schema(1000)
    insert_wallet_trades(db, [_trade("BUY", 100, 0.5)])
    upsert_current_positions(db, [_current_position()])
    insert_closed_positions(db, [_closed_position()])
    db.close()

    assert cli.main(["wallet-flow", "positions", "current", "--wallet", "coinman2"]) == 0
    assert '"current_value": 5.0' in capsys.readouterr().out
    assert cli.main(["wallet-flow", "positions", "report", "--wallet", "coinman2"]) == 0
    output = capsys.readouterr().out
    assert '"closed_positions": 1' in output
    assert '"trades_with_current_position": 1' in output
