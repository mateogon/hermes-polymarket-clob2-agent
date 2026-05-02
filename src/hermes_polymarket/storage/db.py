"""SQLite database access for paper trading."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from hermes_polymarket.data_sources.base import DataEvent
from hermes_polymarket.data_sources.base import EventType
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
        self._run_lightweight_migrations()
        row = self.conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO account (id, starting_balance, cash) VALUES (1, ?, ?)",
                (starting_balance, starting_balance),
            )
        self.conn.commit()

    def _run_lightweight_migrations(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(wallet_scores)")}
        if columns and "warnings_json" not in columns:
            self.conn.execute("ALTER TABLE wallet_scores ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'")

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

    def insert_data_event(self, event: DataEvent) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO data_events
              (source, event_type, event_ts_ms, received_ts_ms, latency_ms, event_key, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.source,
                event.event_type.value,
                event.event_ts_ms,
                event.received_ts_ms,
                event.latency_ms,
                event.key,
                json.dumps(event.payload, sort_keys=True),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def data_events(self, *, source: str | None = None, event_type: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        query = "SELECT * FROM data_events"
        where = []
        values: list[Any] = []
        if source:
            where.append("source = ?")
            values.append(source)
        if event_type:
            where.append("event_type = ?")
            values.append(event_type)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY received_ts_ms DESC, id DESC LIMIT ?"
        values.append(limit)
        return list(self.conn.execute(query, values))

    def upsert_source_health(self, event: DataEvent, *, dropped_events: int = 0) -> None:
        is_error = event.event_type == EventType.SOURCE_HEALTH and event.payload.get("ok") is False
        existing = self.conn.execute("SELECT * FROM source_health WHERE source = ?", (event.source,)).fetchone()
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO source_health
                  (source, last_seen_ts_ms, last_latency_ms, messages_seen, errors_seen, dropped_events, status)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (event.source, event.received_ts_ms, event.latency_ms, 1 if is_error else 0, dropped_events, "error" if is_error else "ok"),
            )
        else:
            self.conn.execute(
                """
                UPDATE source_health
                SET last_seen_ts_ms = ?,
                    last_latency_ms = ?,
                    messages_seen = messages_seen + 1,
                    errors_seen = errors_seen + ?,
                    dropped_events = dropped_events + ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = ?
                """,
                (event.received_ts_ms, event.latency_ms, 1 if is_error else 0, dropped_events, "error" if is_error else "ok", event.source),
            )
        self.conn.commit()

    def source_health(self, source: str | None = None) -> list[sqlite3.Row]:
        if source:
            return list(self.conn.execute("SELECT * FROM source_health WHERE source = ?", (source,)))
        return list(self.conn.execute("SELECT * FROM source_health ORDER BY source"))
