"""SQLite persistence for learning records."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from hermes_polymarket.learning.journal_schema import (
    HypothesisRecord,
    SignalDecisionRecord,
    TradeLifecycleRecord,
)
from hermes_polymarket.storage.db import Database


class DecisionJournal:
    def __init__(self, db: Database):
        self.db = db

    def record_signal_decision(self, record: SignalDecisionRecord) -> None:
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO signal_decisions
              (signal_id, strategy_id, strategy_version, model_version, prompt_version, config_hash,
               code_commit_sha, market_id, condition_id, token_id, outcome, side, source_health_json,
               market_snapshot_json, model_probability_raw, model_probability_adjusted, confidence,
               edge, risk_decision, risk_reason, final_action, human_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.signal_id,
                record.strategy_id,
                record.strategy_version,
                record.model_version,
                record.prompt_version,
                record.config_hash,
                record.code_commit_sha,
                record.market_id,
                record.condition_id,
                record.token_id,
                record.outcome,
                record.side,
                json.dumps(record.source_health, sort_keys=True),
                json.dumps(record.market_snapshot, sort_keys=True),
                record.model_probability_raw,
                record.model_probability_adjusted,
                record.confidence,
                record.edge,
                record.risk_decision,
                record.risk_reason,
                record.final_action,
                record.human_reason,
            ),
        )
        self.db.conn.commit()

    def get_signal_decision(self, signal_id: str) -> sqlite3.Row | None:
        return self.db.conn.execute("SELECT * FROM signal_decisions WHERE signal_id = ?", (signal_id,)).fetchone()

    def record_trade_lifecycle(self, record: TradeLifecycleRecord) -> None:
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO trade_lifecycle
              (trade_id, signal_id, mode, entry_time, entry_expected_price, entry_fill_price,
               entry_slippage, exit_model, exit_time, exit_price, exit_reason, gross_pnl, net_pnl,
               max_adverse_excursion, max_favorable_excursion, status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.trade_id,
                record.signal_id,
                record.mode,
                record.entry_time,
                record.entry_expected_price,
                record.entry_fill_price,
                record.entry_slippage,
                record.exit_model,
                record.exit_time,
                record.exit_price,
                record.exit_reason,
                record.gross_pnl,
                record.net_pnl,
                record.max_adverse_excursion,
                record.max_favorable_excursion,
                record.status,
                json.dumps(record.payload, sort_keys=True),
            ),
        )
        self.db.conn.commit()

    def record_hypothesis(self, record: HypothesisRecord) -> None:
        self.db.conn.execute(
            """
            INSERT OR REPLACE INTO hypotheses
              (hypothesis_id, statement, status, evidence_json, proposed_test_json, result_json, promoted_rule_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.hypothesis_id,
                record.statement,
                record.status,
                json.dumps(record.evidence_ids, sort_keys=True),
                json.dumps(record.proposed_test, sort_keys=True),
                json.dumps(record.result, sort_keys=True),
                record.promoted_rule_id,
            ),
        )
        self.db.conn.commit()

    def hypotheses(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return list(self.db.conn.execute("SELECT * FROM hypotheses WHERE status = ? ORDER BY created_at DESC", (status,)))
        return list(self.db.conn.execute("SELECT * FROM hypotheses ORDER BY created_at DESC"))

