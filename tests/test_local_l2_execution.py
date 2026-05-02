import json

from hermes_polymarket.backtest.local_l2_execution import simulate_local_l2_buy
from hermes_polymarket.storage.db import Database


def test_simulate_local_l2_buy(tmp_path):
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

    result = simulate_local_l2_buy(db, token_id="token", target_ts_ms=1500, amount_usd=5)

    assert result.available is True
    assert result.best_ask == 0.51
    assert result.fill is not None
    assert result.fill.avg_price == 0.51
    db.close()
