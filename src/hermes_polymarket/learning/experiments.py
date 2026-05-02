"""Strategy experiment tracking."""

from __future__ import annotations

import json
import sqlite3

from hermes_polymarket.learning.journal_schema import StrategyExperimentRecord
from hermes_polymarket.storage.db import Database


class ExperimentTracker:
    def __init__(self, db: Database):
        self.db = db

    def record(self, record: StrategyExperimentRecord) -> None:
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO strategy_experiments
              (run_id, run_type, strategy_id, code_commit_sha, config_hash, data_quality,
               dataset_version, parameters_json, metrics_json, artifacts_json, started_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.run_type,
                record.strategy_id,
                record.code_commit_sha,
                record.config_hash,
                record.data_quality,
                record.dataset_version,
                json.dumps(record.parameters, sort_keys=True),
                json.dumps(record.metrics, sort_keys=True),
                json.dumps(record.artifacts, sort_keys=True),
                record.started_at,
                record.ended_at,
            ),
        )
        self.db.conn.commit()

    def runs(self, strategy_id: str | None = None) -> list[sqlite3.Row]:
        if strategy_id:
            return list(self.db.conn.execute("SELECT * FROM strategy_experiments WHERE strategy_id = ? ORDER BY started_at DESC", (strategy_id,)))
        return list(self.db.conn.execute("SELECT * FROM strategy_experiments ORDER BY started_at DESC"))

