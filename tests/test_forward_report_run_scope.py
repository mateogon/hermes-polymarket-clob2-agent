from hermes_polymarket.storage.db import Database
from hermes_polymarket.storage.forward_positions import forward_run_report


def test_forward_report_excludes_fixture_by_default(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    db.conn.execute(
        """
        INSERT INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, token_id, outcome, entry_ts_ms,
           entry_price, shares, amount_usd, status, net_pnl, fixture)
        VALUES
          ('fixture-pos', 's1', 'fixture-run', 'btcusdt', 't', 'YES', 1, 0.5, 10, 5, 'closed', 1.0, 1),
          ('real-pos', 's2', 'real-run', 'ethusdt', 't2', 'UP', 1, 0.5, 10, 5, 'closed', -0.5, 0)
        """
    )
    db.conn.commit()

    report = forward_run_report(db)
    assert report["positions"] == 1
    assert report["net_pnl"] == -0.5

    with_fixture = forward_run_report(db, include_fixture=True)
    assert with_fixture["positions"] == 2
