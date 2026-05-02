"""SQLite helpers for wallet replay inputs and results."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade, parse_wallet_trade
from hermes_polymarket.storage.db import Database


def insert_wallet_trade(db: Database, trade: WalletTrade) -> bool:
    """Insert a public wallet trade.

    Returns True when a new row was inserted and False when it was already
    present. The unique key mirrors the Data API fields that make the observed
    fill stable enough for replay research.
    """

    cur = db.conn.execute(
        """
        INSERT OR IGNORE INTO wallet_observed_trades
          (wallet, condition_id, asset_id, outcome, side, price, size, timestamp,
           slug, title, tx_hash, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.wallet,
            trade.condition_id,
            trade.asset_id,
            trade.outcome,
            trade.side.upper(),
            trade.price,
            trade.size,
            trade.timestamp,
            trade.slug,
            trade.title,
            trade.tx_hash,
            json.dumps(trade.raw, sort_keys=True),
        ),
    )
    db.conn.commit()
    return cur.rowcount > 0


def insert_wallet_trades(db: Database, trades: list[WalletTrade]) -> dict[str, int]:
    inserted = 0
    for trade in trades:
        inserted += int(insert_wallet_trade(db, trade))
    return {"inserted": inserted, "duplicates": len(trades) - inserted, "fetched": len(trades)}


def wallet_trades(
    db: Database,
    wallet: str,
    *,
    limit: int = 1000,
    since_ts: int | None = None,
    condition_id: str | None = None,
) -> list[WalletTrade]:
    clauses = ["LOWER(wallet) = LOWER(?)"]
    values: list[Any] = [wallet]
    if since_ts is not None:
        clauses.append("timestamp >= ?")
        values.append(since_ts)
    if condition_id is not None:
        clauses.append("condition_id = ?")
        values.append(condition_id)
    values.append(limit)
    rows = db.conn.execute(
        f"""
        SELECT * FROM wallet_observed_trades
        WHERE {' AND '.join(clauses)}
        ORDER BY timestamp ASC, id ASC
        LIMIT ?
        """,
        values,
    )
    parsed: list[WalletTrade] = []
    for row in rows:
        raw = json.loads(row["raw_json"] or "{}")
        raw.setdefault("proxyWallet", row["wallet"])
        raw.setdefault("side", row["side"])
        raw.setdefault("conditionId", row["condition_id"])
        raw.setdefault("asset", row["asset_id"])
        raw.setdefault("outcome", row["outcome"])
        raw.setdefault("price", row["price"])
        raw.setdefault("size", row["size"])
        raw.setdefault("timestamp", row["timestamp"])
        raw.setdefault("slug", row["slug"] or "")
        raw.setdefault("title", row["title"] or "")
        raw.setdefault("transactionHash", row["tx_hash"] or "")
        trade = parse_wallet_trade(raw)
        if trade is not None:
            parsed.append(trade)
    return parsed


def clear_wallet_trades(db: Database, wallet: str) -> None:
    db.conn.execute("DELETE FROM wallet_observed_trades WHERE LOWER(wallet) = LOWER(?)", (wallet,))
    db.conn.commit()


def insert_replay_run(
    db: Database,
    *,
    run_id: str,
    wallet: str,
    mode: str,
    data_quality: str,
    delays: list[int],
    config: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO wallet_replay_runs
          (run_id, wallet, mode, data_quality, delays_json, config_json, metrics_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            wallet,
            mode,
            data_quality,
            json.dumps(delays, sort_keys=True),
            json.dumps(config, sort_keys=True),
            json.dumps(metrics or {}, sort_keys=True),
        ),
    )
    db.conn.commit()


def insert_replay_trade(db: Database, data: dict[str, Any]) -> None:
    keys = [
        "replay_trade_id",
        "run_id",
        "wallet",
        "condition_id",
        "asset_id",
        "outcome",
        "delay_seconds",
        "entry_time",
        "entry_price",
        "leader_entry_price",
        "exit_time",
        "exit_price",
        "exit_model",
        "status",
        "pnl",
        "roi",
        "worse_entry_cents",
        "skipped_reason",
        "category",
        "payload_json",
    ]
    values = [data.get(key) for key in keys]
    db.conn.execute(
        f"INSERT OR REPLACE INTO wallet_replay_trades ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        values,
    )
    db.conn.commit()


def replay_runs(db: Database) -> list[sqlite3.Row]:
    return list(db.conn.execute("SELECT * FROM wallet_replay_runs ORDER BY created_at DESC"))


def replay_trades(db: Database, run_id: str | None = None) -> list[sqlite3.Row]:
    if run_id:
        return list(db.conn.execute("SELECT * FROM wallet_replay_trades WHERE run_id = ? ORDER BY delay_seconds, entry_time", (run_id,)))
    return list(db.conn.execute("SELECT * FROM wallet_replay_trades ORDER BY run_id, delay_seconds, entry_time"))


def upsert_wallet_score(
    db: Database,
    *,
    wallet: str,
    score: float,
    components: dict[str, Any],
    sample_size: int,
    warnings: list[str] | None = None,
) -> None:
    db.conn.execute(
        """
        INSERT INTO wallet_scores (wallet, score, warnings_json, components_json, sample_size, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(wallet) DO UPDATE SET
          score = excluded.score,
          warnings_json = excluded.warnings_json,
          components_json = excluded.components_json,
          sample_size = excluded.sample_size,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            wallet,
            score,
            json.dumps(warnings or [], sort_keys=True),
            json.dumps(components, sort_keys=True),
            sample_size,
        ),
    )
    db.conn.commit()


def wallet_scores(db: Database) -> list[sqlite3.Row]:
    return list(db.conn.execute("SELECT * FROM wallet_scores ORDER BY score DESC, sample_size DESC, wallet"))
