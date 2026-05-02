"""Readiness checks before paper strategy arena."""

from __future__ import annotations

from typing import Any

from hermes_polymarket.storage.db import Database


def forward_paper_readiness(
    db: Database,
    *,
    include_fixture: bool = False,
    min_signals: int = 30,
    min_positions: int = 5,
) -> dict[str, Any]:
    fixture_clause = "" if include_fixture else "WHERE fixture = 0"
    signal_row = db.conn.execute(
        f"""
        SELECT
          COUNT(*) AS signals,
          SUM(CASE WHEN final_action != 'paper_fill' THEN 1 ELSE 0 END) AS rejected
        FROM forward_paper_signals
        {fixture_clause}
        """
    ).fetchone()

    position_row = db.conn.execute(
        f"""
        SELECT
          COUNT(*) AS positions,
          SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_positions,
          SUM(CASE WHEN status = 'closed' THEN COALESCE(net_pnl, 0) ELSE 0 END) AS net_pnl
        FROM forward_paper_positions
        {fixture_clause}
        """
    ).fetchone()

    run_row = db.conn.execute(
        f"""
        SELECT
          COUNT(*) AS runs,
          SUM(CASE WHEN exploratory_threshold = 1 THEN 1 ELSE 0 END) AS exploratory_runs
        FROM forward_paper_runs
        {fixture_clause}
        """
    ).fetchone()

    signals = int(signal_row["signals"] or 0)
    rejected = int(signal_row["rejected"] or 0)
    positions = int(position_row["positions"] or 0)
    closed = int(position_row["closed_positions"] or 0)
    net_pnl = float(position_row["net_pnl"] or 0.0)
    runs = int(run_row["runs"] or 0)
    exploratory_runs = int(run_row["exploratory_runs"] or 0)

    clean_rejected_row = db.conn.execute(
        f"""
        SELECT COUNT(*) AS clean_rejected
        FROM forward_paper_signals
        {fixture_clause}
        {'AND' if fixture_clause else 'WHERE'} final_action != 'paper_fill'
          AND COALESCE(risk_reason, '') NOT IN ('lottery_ticket', 'no_executable_fill')
          AND final_action != 'market_quality_rejected'
        """
    ).fetchone()
    clean_rejected = int(clean_rejected_row["clean_rejected"] or 0)

    reasons: list[str] = []
    if signals < min_signals:
        reasons.append(f"signals_real={signals} < {min_signals}" if not include_fixture else f"signals={signals} < {min_signals}")
    if positions < min_positions:
        reasons.append(f"positions_real={positions} < {min_positions}" if not include_fixture else f"positions={positions} < {min_positions}")

    ready_for_diagnostic_arena = positions >= min_positions or signals >= min_signals or clean_rejected >= min_signals

    closed_pnls = [
        float(row["net_pnl"] or 0.0)
        for row in db.conn.execute(
            f"""
            SELECT net_pnl
            FROM forward_paper_positions
            {fixture_clause}
            {'AND' if fixture_clause else 'WHERE'} status = 'closed'
            """
        )
    ]
    dominated_by_one_trade = False
    if closed_pnls and net_pnl != 0:
        dominated_by_one_trade = max(abs(value) for value in closed_pnls) / abs(net_pnl) > 0.5

    ready_for_strategy_claim = (
        closed >= 20
        and signals >= 50
        and net_pnl > 0
        and not dominated_by_one_trade
        and exploratory_runs == 0
    )

    warnings: list[str] = []
    if signals < 50:
        warnings.append("small_signal_sample")
    if positions < 20:
        warnings.append("small_position_sample")
    if exploratory_runs:
        warnings.append("exploratory_threshold")
    if runs < 2:
        warnings.append("single_campaign_window")
    if dominated_by_one_trade:
        warnings.append("dominated_by_one_trade")

    blocking_live_reasons = [
        "insufficient_forward_sample",
        "no_multiday_evidence",
        "no_pre_live_audit",
        "no_canary_design",
    ]

    return {
        "mode": "forward_paper_only",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "ready_for_arena": ready_for_diagnostic_arena,
        "ready_for_diagnostic_arena": ready_for_diagnostic_arena,
        "ready_for_strategy_claim": ready_for_strategy_claim,
        "ready_for_live_review": False,
        "signals_real": signals,
        "positions_real": positions,
        "rejected_real": rejected,
        "clean_rejected_signals": clean_rejected,
        "closed_positions_real": closed,
        "net_pnl": net_pnl,
        "min_signals": min_signals,
        "min_positions": min_positions,
        "reasons": reasons,
        "warnings": warnings,
        "blocking_live_reasons": blocking_live_reasons,
        "next_actions": [
            "run more 0.01 and 0.015 campaigns",
            "add more healthy markets",
            "run diagnostic arena only",
        ],
    }
