"""SQLite database access for paper trading."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from hermes_polymarket.storage.models import SCHEMA


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init_schema(self, starting_balance: float) -> None:
        self.conn.executescript(SCHEMA)
        row = self.conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO account (id, starting_balance, cash) VALUES (1, ?, ?)",
                (starting_balance, starting_balance),
            )
        self.conn.commit()

    def account(self) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("Account not initialized")
        return row

    def update_cash(self, cash: float) -> None:
        self.conn.execute("UPDATE account SET cash = ? WHERE id = 1", (cash,))
        self.conn.commit()

    def add_journal(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO journal (event_type, message, payload_json) VALUES (?, ?, ?)",
            (event_type, message, json.dumps(payload or {}, sort_keys=True)),
        )
        self.conn.commit()

    def insert_trade(self, data: dict[str, Any]) -> int:
        keys = [
            "mode", "market_id", "condition_id", "token_id", "outcome", "side",
            "avg_price", "shares", "amount_usd", "fee", "slippage", "signal_reason",
        ]
        values = [data[k] for k in keys]
        placeholders = ", ".join("?" for _ in keys)
        cur = self.conn.execute(
            f"INSERT INTO trades ({', '.join(keys)}) VALUES ({placeholders})",
            values,
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_position(self, *, market_id: str, condition_id: str, token_id: str, outcome: str, shares: float, cost: float, avg_price: float) -> None:
        existing = self.conn.execute(
            "SELECT * FROM positions WHERE condition_id = ? AND token_id = ? AND outcome = ? AND status = 'open'",
            (condition_id, token_id, outcome),
        ).fetchone()
        if existing:
            total_shares = float(existing["shares"]) + shares
            total_cost = float(existing["total_cost"]) + cost
            new_avg = total_cost / total_shares if total_shares else 0.0
            self.conn.execute(
                "UPDATE positions SET shares = ?, total_cost = ?, avg_entry_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (total_shares, total_cost, new_avg, existing["id"]),
            )
        else:
            self.conn.execute(
                "INSERT INTO positions (market_id, condition_id, token_id, outcome, shares, avg_entry_price, total_cost) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (market_id, condition_id, token_id, outcome, shares, avg_price, cost),
            )
        self.conn.commit()

    def open_positions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM positions WHERE status = 'open'"))

    def trades(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM trades ORDER BY id"))

