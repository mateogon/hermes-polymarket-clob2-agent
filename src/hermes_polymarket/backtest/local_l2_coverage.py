"""Coverage summaries for locally recorded L2 data."""

from __future__ import annotations

from typing import Any

from hermes_polymarket.storage.db import Database


def local_l2_coverage_report(db: Database, *, token_id: str | None = None) -> dict[str, Any]:
    where = ""
    params: tuple[str, ...] = ()
    if token_id:
        where = "WHERE token_id = ?"
        params = (token_id,)

    snapshots = db.conn.execute(f"SELECT COUNT(*) AS n FROM l2_book_snapshots {where}", params).fetchone()["n"]
    deltas = db.conn.execute(f"SELECT COUNT(*) AS n FROM l2_price_changes {where}", params).fetchone()["n"]
    bbo = db.conn.execute(f"SELECT COUNT(*) AS n FROM l2_bbo_updates {where}", params).fetchone()["n"]
    first_ts = db.conn.execute(
        f"""
        SELECT MIN(received_ts_ms) AS n FROM (
          SELECT received_ts_ms FROM l2_book_snapshots {where}
          UNION ALL
          SELECT received_ts_ms FROM l2_price_changes {where}
          UNION ALL
          SELECT received_ts_ms FROM l2_bbo_updates {where}
        )
        """,
        params * 3,
    ).fetchone()["n"]
    last_ts = db.conn.execute(
        f"""
        SELECT MAX(received_ts_ms) AS n FROM (
          SELECT received_ts_ms FROM l2_book_snapshots {where}
          UNION ALL
          SELECT received_ts_ms FROM l2_price_changes {where}
          UNION ALL
          SELECT received_ts_ms FROM l2_bbo_updates {where}
        )
        """,
        params * 3,
    ).fetchone()["n"]

    return {
        "data_quality": "local_l2",
        "token_id": token_id,
        "snapshots": int(snapshots),
        "deltas": int(deltas),
        "bbo_updates": int(bbo),
        "first_received_ts_ms": first_ts,
        "last_received_ts_ms": last_ts,
    }
