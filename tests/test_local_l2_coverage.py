import json

from hermes_polymarket.backtest.local_l2_coverage import local_l2_coverage_report
from hermes_polymarket.storage.db import Database


def test_local_l2_coverage_report(tmp_path):
    db = Database(tmp_path / "x.sqlite")
    db.init_schema(1000)
    db.conn.execute(
        "INSERT INTO l2_book_snapshots (token_id, received_ts_ms, bids_json, asks_json) VALUES (?, ?, ?, ?)",
        ("token", 1000, json.dumps([]), json.dumps([])),
    )
    db.conn.commit()

    report = local_l2_coverage_report(db, token_id="token")

    assert report["data_quality"] == "local_l2"
    assert report["snapshots"] == 1
    db.close()
