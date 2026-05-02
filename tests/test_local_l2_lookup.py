import json

from hermes_polymarket.backtest.local_l2_lookup import nearest_bbo_before, reconstruct_book_at
from hermes_polymarket.storage.db import Database


def test_reconstruct_book_applies_remove_delta(tmp_path):
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
            json.dumps([{"price": "0.49", "size": "10"}]),
            json.dumps([{"price": "0.51", "size": "10"}]),
        ),
    )
    db.conn.execute(
        """
        INSERT INTO l2_price_changes
          (token_id, side, price, size, removed, received_ts_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("token", "ask", 0.51, 0.0, 1, 1500),
    )
    db.conn.commit()

    state = reconstruct_book_at(db, token_id="token", target_ts_ms=2000)

    assert state is not None
    assert state.by_token["token"].best_ask is None
    assert state.by_token["token"].best_bid == 0.49
    db.close()


def test_nearest_bbo_before(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    db.conn.execute(
        """
        INSERT INTO l2_bbo_updates
          (token_id, best_bid, best_ask, spread, received_ts_ms)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("token", 0.49, 0.51, 0.02, 1000),
    )
    db.conn.commit()

    row = nearest_bbo_before(db, token_id="token", target_ts_ms=1500)

    assert row is not None
    assert row["best_ask"] == 0.51
    db.close()
