"""SQLite helpers for wallet replay results."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from hermes_polymarket.storage.db import Database


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

