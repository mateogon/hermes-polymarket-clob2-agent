from hermes_polymarket.forward_paper.shadow_exit_replay import replay_position_exit, shadow_exit_grid
from hermes_polymarket.storage.db import Database


def test_shadow_exit_take_profit_closes_earlier():
    position = {"entry_price": 0.5, "shares": 10, "entry_ts_ms": 1000, "marks": [{"ts_ms": 2000, "mark_price": 0.56}]}
    out = replay_position_exit(position, take_profit_cents=5, stop_loss_cents=4, timeout_seconds=900)
    assert out["exit_reason"] == "take_profit"
    assert out["net_pnl"] == 0.6000000000000005


def test_shadow_exit_stop_loss_closes_earlier():
    position = {"entry_price": 0.5, "shares": 10, "entry_ts_ms": 1000, "marks": [{"ts_ms": 2000, "mark_price": 0.46}]}
    out = replay_position_exit(position, take_profit_cents=5, stop_loss_cents=4, timeout_seconds=900)
    assert out["exit_reason"] == "stop_loss"


def test_shadow_exit_timeout_closes():
    position = {"entry_price": 0.5, "shares": 10, "entry_ts_ms": 1000, "marks": [{"ts_ms": 62_000, "mark_price": 0.51}]}
    out = replay_position_exit(position, take_profit_cents=5, stop_loss_cents=4, timeout_seconds=60)
    assert out["exit_reason"] == "timeout"


def test_shadow_exit_grid_does_not_modify_positions(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, status, exit_ts_ms,
           exit_price, exit_reason, gross_pnl, net_pnl, fixture)
        VALUES ('p', 's', 'r', 'btcusdt', 'c', 't', 'YES', 1000, 0.5, 10, 5, 'closed', 2000, 0.6, 'take_profit', 1, 1, 0)
        """
    )
    db.conn.execute(
        "INSERT INTO forward_paper_marks (position_id, ts_ms, mark_price, best_bid, best_ask, unrealized_pnl) VALUES ('p', 2000, 0.6, 0.6, 0.61, 1)"
    )
    db.conn.commit()
    db.close()
    out = shadow_exit_grid([tmp_path / "x.sqlite3"], take_profit_cents=[5], stop_loss_cents=[4], timeout_seconds=[60])
    assert out["current_config"]["net_pnl"] == 1
    assert out["best_config"]["positions"] == 1
