from hermes_polymarket.forward_paper.loss_attribution import loss_attribution
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import insert_forward_run, insert_forward_signal


def _db(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    db.init_schema(1000)
    return db


def test_loss_attribution_groups_and_excludes_fixture(tmp_path):
    db = _db(tmp_path)
    insert_forward_run(db, run_id="r", symbols=("btcusdt",), config={"min_move_pct": 0.01}, summary={}, report={}, quality={}, artifacts={})
    insert_forward_signal(
        db,
        {
            "signal_id": "s",
            "run_id": "r",
            "symbol": "btcusdt",
            "condition_id": "c",
            "token_id": "t",
            "outcome": "YES",
            "direction": "up",
            "external_move_ts_ms": 1,
            "external_move_pct": 0.02,
            "final_action": "paper_fill",
            "risk_reason": "allowed",
            "amount_usd": 5,
            "fixture": False,
        },
    )
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, status, exit_ts_ms,
           exit_price, exit_reason, gross_pnl, net_pnl, fixture)
        VALUES
          ('p', 's', 'r', 'btcusdt', 'c', 't', 'YES', 1, 0.5, 10, 5, 'closed', 2, 0.4, 'stop_loss', -1, -1, 0),
          ('pf', 's', 'r', 'btcusdt', 'c', 't', 'YES', 1, 0.5, 10, 5, 'closed', 2, 0.7, 'take_profit', 2, 2, 1)
        """
    )
    db.conn.commit()
    db.close()

    out = loss_attribution([tmp_path / "x.sqlite3"])
    assert out["positions"] == 1
    assert out["net_pnl"] == -1
    assert out["by_threshold"]["0.01"]["positions"] == 1
    assert out["by_symbol"]["btcusdt"]["net_pnl"] == -1
    assert "threshold_only_signal_too_noisy" in out["dominant_loss_hypotheses"]


def test_loss_attribution_handles_empty_db(tmp_path):
    db = _db(tmp_path)
    db.close()
    out = loss_attribution([tmp_path / "x.sqlite3"])
    assert out["positions"] == 0
    assert out["net_pnl"] == 0
