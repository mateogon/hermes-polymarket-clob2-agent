"""Storage helpers for forward paper lifecycle tracking."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.forward_paper.lifecycle import ForwardPaperPosition
from hermes_polymarket.storage.db import Database


def upsert_forward_position(db: Database, pos: ForwardPaperPosition, payload: dict[str, Any] | None = None) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, best_bid_at_entry,
           best_ask_at_entry, spread_at_entry, status, exit_ts_ms, exit_price,
           exit_reason, gross_pnl, net_pnl, max_favorable_excursion,
           max_adverse_excursion, data_quality, payload_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            pos.position_id,
            pos.signal_id,
            pos.run_id,
            pos.symbol,
            pos.condition_id,
            pos.token_id,
            pos.outcome,
            pos.entry_ts_ms,
            pos.entry_price,
            pos.shares,
            pos.amount_usd,
            pos.best_bid_at_entry,
            pos.best_ask_at_entry,
            pos.spread_at_entry,
            pos.status,
            pos.exit_ts_ms,
            pos.exit_price,
            pos.exit_reason,
            pos.gross_pnl,
            pos.net_pnl,
            pos.max_favorable_excursion,
            pos.max_adverse_excursion,
            pos.data_quality,
            json.dumps(payload or {}, sort_keys=True),
        ),
    )
    db.conn.commit()


def open_forward_positions(db: Database, *, run_id: str | None = None) -> list[dict[str, Any]]:
    if run_id:
        rows = db.conn.execute(
            "SELECT * FROM forward_paper_positions WHERE status='open' AND run_id=? ORDER BY entry_ts_ms DESC",
            (run_id,),
        )
    else:
        rows = db.conn.execute("SELECT * FROM forward_paper_positions WHERE status='open' ORDER BY entry_ts_ms DESC")
    return [dict(row) for row in rows]


def forward_positions(db: Database, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if status:
        rows = db.conn.execute(
            "SELECT * FROM forward_paper_positions WHERE status=? ORDER BY entry_ts_ms DESC LIMIT ?",
            (status, limit),
        )
    else:
        rows = db.conn.execute(
            "SELECT * FROM forward_paper_positions ORDER BY entry_ts_ms DESC LIMIT ?",
            (limit,),
        )
    return [dict(row) for row in rows]


def insert_forward_mark(
    db: Database,
    *,
    position_id: str,
    ts_ms: int,
    mark_price: float | None,
    best_bid: float | None,
    best_ask: float | None,
    unrealized_pnl: float | None,
    payload: dict[str, Any] | None = None,
) -> None:
    db.conn.execute(
        """
        INSERT INTO forward_paper_marks
          (position_id, ts_ms, mark_price, best_bid, best_ask, unrealized_pnl, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position_id,
            ts_ms,
            mark_price,
            best_bid,
            best_ask,
            unrealized_pnl,
            json.dumps(payload or {}, sort_keys=True),
        ),
    )
    db.conn.commit()


def forward_position_report(db: Database) -> dict[str, Any]:
    rows = db.conn.execute("SELECT * FROM forward_paper_positions").fetchall()
    closed = [dict(row) for row in rows if row["status"] == "closed"]
    open_ = [dict(row) for row in rows if row["status"] == "open"]
    pnl = sum(float(row["net_pnl"] or 0.0) for row in closed)
    return {
        "mode": "forward_paper_only",
        "data_quality": "paper_live",
        "positions": len(rows),
        "open": len(open_),
        "closed": len(closed),
        "net_pnl": pnl,
        "win_rate": sum(1 for row in closed if float(row["net_pnl"] or 0.0) > 0) / len(closed) if closed else 0.0,
    }


def insert_forward_run(
    db: Database,
    *,
    run_id: str,
    symbols: tuple[str, ...],
    config: dict[str, Any],
    summary: dict[str, Any],
    report: dict[str, Any],
    quality: dict[str, Any],
    artifacts: dict[str, Any],
) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO forward_paper_runs
          (run_id, symbols_json, config_json, summary_json, report_json, quality_json, artifacts_json, ended_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            run_id,
            json.dumps(list(symbols), sort_keys=True),
            json.dumps(config, sort_keys=True),
            json.dumps(summary, sort_keys=True),
            json.dumps(report, sort_keys=True),
            json.dumps(quality, sort_keys=True),
            json.dumps(artifacts, sort_keys=True),
        ),
    )
    db.conn.commit()


def forward_runs(db: Database, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT * FROM forward_paper_runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def forward_run(db: Database, run_id: str) -> dict[str, Any] | None:
    row = db.conn.execute("SELECT * FROM forward_paper_runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def forward_signals_for_run(db: Database, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        """
        SELECT * FROM crypto_latency_events
        WHERE payload_json LIKE ?
        ORDER BY external_move_detected_ts_ms DESC
        LIMIT ?
        """,
        (f"%{run_id}%", limit),
    )
    return [dict(row) for row in rows]
