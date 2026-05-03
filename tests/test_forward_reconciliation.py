from hermes_polymarket.forward_paper.reconciliation import reconcile_open_positions
from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import forward_run_report


def _insert_open_position(db: Database, *, token_id: str = "token") -> None:
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, token_id, outcome, entry_ts_ms,
           entry_price, shares, amount_usd, best_bid_at_entry, best_ask_at_entry,
           spread_at_entry, status, data_quality, fixture)
        VALUES
          ('pos-1', 'sig-1', 'run-1', 'btcusdt', ?, 'YES', 1000,
           0.50, 10, 5, 0.49, 0.50, 0.01, 'open', 'paper_live', 0)
        """,
        (token_id,),
    )
    db.conn.commit()


def test_reconcile_open_marks_position_to_latest_bid(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    _insert_open_position(db)
    db.conn.execute(
        """
        INSERT INTO l2_bbo_updates
          (token_id, best_bid, best_ask, spread, received_ts_ms)
        VALUES
          ('token', 0.42, 0.43, 0.01, 2000)
        """
    )
    db.conn.commit()

    result = reconcile_open_positions(db, run_id="run-1", policy="mark_to_last_bid")

    assert result["closed"] == 1
    row = db.conn.execute("SELECT * FROM forward_paper_positions WHERE position_id='pos-1'").fetchone()
    assert row["status"] == "closed"
    assert row["exit_reason"] == "run_end_mark"
    assert row["exit_price"] == 0.42
    assert row["data_quality"] == "paper_live_mark_to_market"


def test_reconcile_open_keeps_open_without_mark(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    _insert_open_position(db)

    result = reconcile_open_positions(db, run_id="run-1", policy="mark_to_last_bid")

    assert result["closed"] == 0
    assert result["kept_open"] == 1
    assert "no_mark_available" in result["warnings"]
    row = db.conn.execute("SELECT * FROM forward_paper_positions WHERE position_id='pos-1'").fetchone()
    assert row["status"] == "open"


def test_reconcile_open_ignores_mark_before_entry(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    _insert_open_position(db)
    db.conn.execute(
        "INSERT INTO l2_bbo_updates (token_id, best_bid, received_ts_ms) VALUES ('token', 0.42, 900)"
    )
    db.conn.commit()

    result = reconcile_open_positions(db, run_id="run-1", policy="mark_to_last_bid")

    assert result["closed"] == 0
    assert result["kept_open"] == 1
    row = db.conn.execute("SELECT * FROM forward_paper_positions WHERE position_id='pos-1'").fetchone()
    assert row["status"] == "open"


def test_forward_report_warns_on_run_end_mark(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    _insert_open_position(db)
    db.conn.execute(
        "INSERT INTO l2_bbo_updates (token_id, best_bid, received_ts_ms) VALUES ('token', 0.42, 2000)"
    )
    db.conn.commit()
    reconcile_open_positions(db, run_id="run-1")

    report = forward_run_report(db, run_id="run-1")

    assert report["closed"] == 1
    assert report["mark_to_market_positions"] == 1
    assert "mark_to_market_exit_not_actual_fill" in report["quality_warnings"]
