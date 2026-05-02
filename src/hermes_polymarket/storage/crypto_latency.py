"""SQLite helpers for crypto latency measurement."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.storage.db import Database


def insert_crypto_market_window(db: Database, row: dict[str, Any]) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO crypto_market_windows
          (condition_id, slug, question, symbol, yes_token_id, no_token_id,
           window_start_ts, window_end_ts, reference_price, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["condition_id"],
            row["slug"],
            row.get("question"),
            row["symbol"],
            row["yes_token_id"],
            row["no_token_id"],
            row.get("window_start_ts"),
            row.get("window_end_ts"),
            row.get("reference_price"),
            int(row.get("active", True)),
        ),
    )
    db.conn.commit()


def insert_crypto_consensus_tick(
    db: Database,
    *,
    symbol: str,
    consensus_price: float,
    sources: tuple[str, ...],
    max_deviation_pct: float,
    received_ts_ms: int,
) -> int:
    cur = db.conn.execute(
        """
        INSERT INTO crypto_consensus_ticks
          (symbol, consensus_price, sources_json, max_deviation_pct, received_ts_ms)
        VALUES (?, ?, ?, ?, ?)
        """,
        (symbol, consensus_price, json.dumps(list(sources)), max_deviation_pct, received_ts_ms),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def insert_crypto_latency_event(db: Database, event: dict[str, Any]) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO crypto_latency_events
          (event_id, symbol, condition_id, external_move_pct, external_move_detected_ts_ms,
           polymarket_reprice_ts_ms, repricing_lag_ms, spread_before, depth_before_usd,
           stale_quote_depth_usd, source_health_json, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["event_id"],
            event["symbol"],
            event.get("condition_id"),
            event["external_move_pct"],
            event["external_move_detected_ts_ms"],
            event.get("polymarket_reprice_ts_ms"),
            event.get("repricing_lag_ms"),
            event.get("spread_before"),
            event.get("depth_before_usd"),
            event.get("stale_quote_depth_usd"),
            json.dumps(event.get("source_health", {}), sort_keys=True),
            json.dumps(event.get("payload", {}), sort_keys=True),
        ),
    )
    db.conn.commit()


def insert_crypto_latency_opportunity(db: Database, row: dict[str, Any]) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO crypto_latency_opportunities
          (opportunity_id, event_id, token_id, outcome, side, amount_usd,
           avg_price, shares, fill_status, risk_allowed, risk_reason,
           data_quality, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["opportunity_id"],
            row["event_id"],
            row["token_id"],
            row["outcome"],
            row["side"],
            row["amount_usd"],
            row.get("avg_price"),
            row.get("shares"),
            row["fill_status"],
            int(row["risk_allowed"]),
            row.get("risk_reason"),
            row.get("data_quality", "paper_live"),
            json.dumps(row.get("payload", {}), sort_keys=True),
        ),
    )
    db.conn.commit()


def crypto_latency_events(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT * FROM crypto_latency_events ORDER BY external_move_detected_ts_ms DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def crypto_latency_opportunities(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT * FROM crypto_latency_opportunities ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def crypto_latency_report(db: Database) -> dict[str, Any]:
    total = db.conn.execute("SELECT COUNT(*) AS n FROM crypto_latency_events").fetchone()["n"]
    opps = db.conn.execute("SELECT COUNT(*) AS n FROM crypto_latency_opportunities").fetchone()["n"]
    ticks = db.conn.execute("SELECT COUNT(*) AS n FROM crypto_consensus_ticks").fetchone()["n"]
    windows = db.conn.execute("SELECT COUNT(*) AS n FROM crypto_market_windows").fetchone()["n"]
    by_symbol = db.conn.execute(
        """
        SELECT symbol, COUNT(*) AS n
        FROM crypto_latency_events
        GROUP BY symbol
        ORDER BY n DESC
        """
    ).fetchall()
    return {
        "mode": "measurement_paper_only",
        "events": int(total),
        "opportunities": int(opps),
        "consensus_ticks": int(ticks),
        "market_windows": int(windows),
        "by_symbol": {row["symbol"]: int(row["n"]) for row in by_symbol},
    }
