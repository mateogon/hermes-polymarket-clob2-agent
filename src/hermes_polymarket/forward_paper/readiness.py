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
          SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_positions
        FROM forward_paper_positions
        {fixture_clause}
        """
    ).fetchone()

    signals = int(signal_row["signals"] or 0)
    rejected = int(signal_row["rejected"] or 0)
    positions = int(position_row["positions"] or 0)
    closed = int(position_row["closed_positions"] or 0)

    reasons: list[str] = []
    if signals < min_signals:
        reasons.append(f"signals_real={signals} < {min_signals}" if not include_fixture else f"signals={signals} < {min_signals}")
    if positions < min_positions:
        reasons.append(f"positions_real={positions} < {min_positions}" if not include_fixture else f"positions={positions} < {min_positions}")

    return {
        "mode": "forward_paper_only",
        "data_quality": "paper_live",
        "include_fixture": include_fixture,
        "ready_for_arena": not reasons,
        "signals_real": signals,
        "positions_real": positions,
        "rejected_real": rejected,
        "closed_positions_real": closed,
        "min_signals": min_signals,
        "min_positions": min_positions,
        "reasons": reasons,
        "next_actions": [] if not reasons else [
            "run parallel threshold collection",
            "add more watchlist markets",
            "inspect max_slippage rejections",
        ],
    }
