from hermes_polymarket.backtest.wallet_replay_storage import insert_replay_run, insert_replay_trade, replay_runs, replay_trades
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
