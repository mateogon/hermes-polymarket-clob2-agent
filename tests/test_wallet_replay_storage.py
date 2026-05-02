from hermes_polymarket.backtest.wallet_replay_storage import (
    clear_wallet_trades,
    insert_replay_run,
    insert_replay_trade,
    insert_wallet_trades,
    replay_runs,
    replay_trades,
    upsert_wallet_score,
    wallet_scores,
    wallet_trades,
)
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.storage.db import Database


def test_wallet_replay_storage_roundtrip(tmp_path):
    db = Database(tmp_path / "replay.sqlite3")
    db.init_schema(1000)
    insert_replay_run(
        db,
        run_id="run1",
        wallet="coinman2",
        mode="historical_approx",
        data_quality="historical_approx",
        delays=[0, 2],
        config={"amount": 5},
        metrics={"observed": 1},
    )
    insert_replay_trade(
        db,
        {
            "replay_trade_id": "rt1",
            "run_id": "run1",
            "wallet": "coinman2",
            "condition_id": "c",
            "asset_id": "a",
            "outcome": "Yes",
            "delay_seconds": 2,
            "entry_time": 100,
            "entry_price": 0.52,
            "leader_entry_price": 0.5,
            "exit_time": 200,
            "exit_price": 0.7,
            "exit_model": "leader_exit",
            "status": "closed",
            "pnl": 1.7,
            "roi": 0.34,
            "worse_entry_cents": 2.0,
            "skipped_reason": None,
            "category": "crypto",
            "payload_json": "{}",
        },
    )
    assert replay_runs(db)[0]["run_id"] == "run1"
    assert replay_trades(db, "run1")[0]["pnl"] == 1.7
    db.close()


def observed_trade(tx="tx", ts=100):
    return WalletTrade(
        wallet="0xabc",
        side="BUY",
        condition_id="c",
        asset_id="a",
        outcome="Yes",
        price=0.5,
        size=10,
        timestamp=ts,
        slug="slug",
        title="title",
        tx_hash=tx,
        raw={
            "proxyWallet": "0xabc",
            "side": "BUY",
            "conditionId": "c",
            "asset": "a",
            "outcome": "Yes",
            "price": 0.5,
            "size": 10,
            "timestamp": ts,
            "slug": "slug",
            "title": "title",
            "transactionHash": tx,
        },
    )


def test_wallet_observed_trades_persist_and_dedupe(tmp_path):
    db = Database(tmp_path / "observed.sqlite3")
    db.init_schema(1000)
    counts = insert_wallet_trades(db, [observed_trade(), observed_trade()])
    assert counts == {"fetched": 2, "inserted": 1, "duplicates": 1}
    rows = wallet_trades(db, "0xabc")
    assert len(rows) == 1
    assert rows[0].condition_id == "c"
    clear_wallet_trades(db, "0xabc")
    assert wallet_trades(db, "0xabc") == []
    db.close()


def test_wallet_scores_roundtrip(tmp_path):
    db = Database(tmp_path / "scores.sqlite3")
    db.init_schema(1000)
    upsert_wallet_score(db, wallet="0xabc", score=0.42, components={"sample_size": 0.1}, sample_size=2, warnings=["small_sample"])
    rows = wallet_scores(db)
    assert rows[0]["wallet"] == "0xabc"
    assert rows[0]["warnings_json"] == '["small_sample"]'
    db.close()
