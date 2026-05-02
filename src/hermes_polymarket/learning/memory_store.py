"""Long-term memory store for learning records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from hermes_polymarket.learning.journal_schema import MemoryType
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    memory_type: MemoryType
    status: str
    content: dict[str, Any]
    evidence: dict[str, Any]
    strategy_id: str | None = None
    wallet: str | None = None
    market_category: str | None = None
    confidence: float = 0.0
    active_in_paper: bool = False
    active_in_live: bool = False

    def __post_init__(self) -> None:
        if self.active_in_live:
            raise ValueError("Memories cannot activate live behavior")
        if self.memory_type not in {"episodic", "semantic", "procedural"}:
            raise ValueError("invalid memory_type")


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def put(self, record: MemoryRecord) -> None:
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO agent_memories
              (memory_id, memory_type, status, strategy_id, wallet, market_category,
               content_json, evidence_json, confidence, active_in_paper, active_in_live)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.memory_id,
                record.memory_type,
                record.status,
                record.strategy_id,
                record.wallet,
                record.market_category,
                json.dumps(record.content, sort_keys=True),
                json.dumps(record.evidence, sort_keys=True),
                record.confidence,
                int(record.active_in_paper),
                int(record.active_in_live),
            ),
        )
        self.db.conn.commit()

    def search(
        self,
        *,
        query: str | None = None,
        memory_type: str | None = None,
        strategy_id: str | None = None,
        wallet: str | None = None,
        market_category: str | None = None,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        values: list[Any] = []
        if memory_type:
            clauses.append("memory_type = ?")
            values.append(memory_type)
        if strategy_id:
            clauses.append("strategy_id = ?")
            values.append(strategy_id)
        if wallet:
            clauses.append("wallet = ?")
            values.append(wallet)
        if market_category:
            clauses.append("market_category = ?")
            values.append(market_category)
        if query:
            clauses.append("(content_json LIKE ? OR evidence_json LIKE ?)")
            values.extend([f"%{query}%", f"%{query}%"])
        sql = "SELECT * FROM agent_memories"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        values.append(limit)
        return list(self.db.conn.execute(sql, values))
