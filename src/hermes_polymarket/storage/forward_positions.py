"""Storage helpers for forward paper lifecycle tracking."""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.forward_paper.lifecycle import ForwardPaperPosition
from hermes_polymarket.storage.db import Database


def upsert_forward_position(db: Database, pos: ForwardPaperPosition, payload: dict[str, Any] | None = None, *, fixture: bool = False) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO forward_paper_positions
          (position_id, signal_id, run_id, symbol, condition_id, token_id, outcome,
           entry_ts_ms, entry_price, shares, amount_usd, best_bid_at_entry,
           best_ask_at_entry, spread_at_entry, status, exit_ts_ms, exit_price,
           exit_reason, gross_pnl, net_pnl, max_favorable_excursion,
           max_adverse_excursion, data_quality, fixture, payload_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
            int(fixture),
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


def forward_positions(
    db: Database,
    *,
    run_id: str | None = None,
    status: str | None = None,
    include_fixture: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        values.append(run_id)
    if status:
        clauses.append("status = ?")
        values.append(status)
    if not include_fixture:
        clauses.append("fixture = 0")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.conn.execute(
        f"SELECT * FROM forward_paper_positions {where} ORDER BY entry_ts_ms DESC LIMIT ?",
        (*values, limit),
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


def insert_forward_signal(db: Database, row: dict[str, Any]) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO forward_paper_signals
          (signal_id, run_id, symbol, condition_id, token_id, outcome, direction,
           external_move_ts_ms, external_move_pct, final_action, risk_reason, fill_status,
           best_bid, best_ask, spread, avg_price, shares, amount_usd, model_probability,
           data_quality, fixture, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["signal_id"],
            row["run_id"],
            row["symbol"],
            row.get("condition_id"),
            row.get("token_id"),
            row.get("outcome"),
            row.get("direction"),
            row["external_move_ts_ms"],
            row.get("external_move_pct"),
            row["final_action"],
            row.get("risk_reason"),
            row.get("fill_status"),
            row.get("best_bid"),
            row.get("best_ask"),
            row.get("spread"),
            row.get("avg_price"),
            row.get("shares"),
            row["amount_usd"],
            row.get("model_probability"),
            row.get("data_quality", "paper_live"),
            int(row.get("fixture", False)),
            json.dumps(row.get("payload", {}), sort_keys=True),
        ),
    )
    db.conn.commit()


def forward_signals(
    db: Database,
    *,
    run_id: str | None = None,
    include_fixture: bool = False,
    rejected_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        values.append(run_id)
    if not include_fixture:
        clauses.append("fixture = 0")
    if rejected_only:
        clauses.append("final_action != 'paper_fill'")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.conn.execute(
        f"SELECT * FROM forward_paper_signals {where} ORDER BY created_at DESC LIMIT ?",
        (*values, limit),
    )
    return [dict(row) for row in rows]


def forward_run_report(db: Database, *, run_id: str | None = None, include_fixture: bool = False) -> dict[str, Any]:
    signals = forward_signals(db, run_id=run_id, include_fixture=include_fixture, limit=10_000)
    positions = forward_positions(db, run_id=run_id, include_fixture=include_fixture, limit=10_000)
    closed = [row for row in positions if row["status"] == "closed"]
    open_ = [row for row in positions if row["status"] == "open"]
    by_action_reason: dict[str, int] = {}
    for signal in signals:
        key = f"{signal.get('final_action')}:{signal.get('risk_reason')}"
        by_action_reason[key] = by_action_reason.get(key, 0) + 1
    pnl = sum(float(row["net_pnl"] or 0.0) for row in closed)
    return {
        "mode": "forward_paper_only",
        "data_quality": "paper_live",
        "run_id": run_id,
        "include_fixture": include_fixture,
        "signals": len(signals),
        "positions": len(positions),
        "open": len(open_),
        "closed": len(closed),
        "net_pnl": pnl,
        "win_rate": sum(1 for row in closed if float(row["net_pnl"] or 0.0) > 0) / len(closed) if closed else 0.0,
        "by_action_reason": by_action_reason,
    }


def forward_position_report(db: Database, *, run_id: str | None = None, include_fixture: bool = False) -> dict[str, Any]:
    return forward_run_report(db, run_id=run_id, include_fixture=include_fixture)


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
    requested_symbols: tuple[str, ...] | None = None,
    requested_seconds: int | None = None,
    actual_seconds: int | None = None,
    fixture: bool = False,
    exploratory_threshold: bool = False,
) -> None:
    db.conn.execute(
        """
        INSERT OR REPLACE INTO forward_paper_runs
          (run_id, symbols_json, requested_symbols_json, requested_seconds, actual_seconds,
           fixture, exploratory_threshold, config_json, summary_json, report_json,
           quality_json, artifacts_json, ended_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            run_id,
            json.dumps(list(symbols), sort_keys=True),
            json.dumps(list(requested_symbols or symbols), sort_keys=True),
            requested_seconds,
            actual_seconds,
            int(fixture),
            int(exploratory_threshold),
            json.dumps(config, sort_keys=True),
            json.dumps(summary, sort_keys=True),
            json.dumps(report, sort_keys=True),
            json.dumps(quality, sort_keys=True),
            json.dumps(artifacts, sort_keys=True),
        ),
    )
    db.conn.commit()


def forward_runs(db: Database, *, include_fixture: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    where = "" if include_fixture else "WHERE fixture = 0"
    rows = db.conn.execute(
        f"SELECT * FROM forward_paper_runs {where} ORDER BY started_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def forward_run(db: Database, run_id: str) -> dict[str, Any] | None:
    row = db.conn.execute("SELECT * FROM forward_paper_runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def forward_signals_for_run(db: Database, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    return forward_signals(db, run_id=run_id, include_fixture=True, limit=limit)
