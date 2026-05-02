import json

from hermes_polymarket.backtest.wallet_replay_local_l2 import replay_wallet_trades_local_l2
from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayRunConfig
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.storage.db import Database


def _trade() -> WalletTrade:
    return WalletTrade(
        wallet="0xabc",
        side="BUY",
        condition_id="condition",
        asset_id="token",
        outcome="Yes",
        price=0.5,
        size=10,
        timestamp=1,
        slug="slug",
        title="title",
        tx_hash="tx",
        raw={},
    )


def test_wallet_replay_local_l2_skips_without_book(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    config = ReplayRunConfig(wallet="0xabc", mode="local_l2", data_quality="local_l2", exit_model=ExitModel.LEADER_EXIT)

    results = replay_wallet_trades_local_l2(db, [_trade()], config, run_id="run")

    assert results[0].status == "skipped"
    assert results[0].skipped_reason == "no_l2_book_at_timestamp"
    db.close()


def test_wallet_replay_local_l2_uses_book(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    db.conn.execute(
        """
        INSERT INTO l2_book_snapshots
          (token_id, received_ts_ms, bids_json, asks_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            "token",
            1000,
            json.dumps([{"price": "0.49", "size": "100"}]),
            json.dumps([{"price": "0.51", "size": "100"}]),
        ),
    )
    db.conn.commit()
    config = ReplayRunConfig(wallet="0xabc", mode="local_l2", data_quality="local_l2", exit_model=ExitModel.LEADER_EXIT)

    results = replay_wallet_trades_local_l2(db, [_trade()], config, run_id="run")

    assert results[0].entry_price == 0.51
    assert results[0].payload["data_quality"] == "local_l2"
    db.close()
