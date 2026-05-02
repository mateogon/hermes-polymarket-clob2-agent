"""Position-based wallet intelligence reports."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def closed_position_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_realized = sum(float(row["realized_pnl"]) for row in rows)
    total_bought = sum(float(row["total_bought"]) for row in rows)
    wins = [row for row in rows if float(row["realized_pnl"]) > 0]
    losses = [row for row in rows if float(row["realized_pnl"]) < 0]

    by_slug: dict[str, float] = defaultdict(float)
    by_outcome: dict[str, float] = defaultdict(float)
    for row in rows:
        by_slug[str(row.get("slug") or "unknown")] += float(row["realized_pnl"])
        by_outcome[str(row.get("outcome") or "unknown")] += float(row["realized_pnl"])

    return {
        "closed_positions": len(rows),
        "total_realized_pnl": total_realized,
        "total_bought": total_bought,
        "roi_on_total_bought": total_realized / total_bought if total_bought else 0.0,
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "wins": len(wins),
        "losses": len(losses),
        "top_slug_pnl": sorted(by_slug.items(), key=lambda item: item[1], reverse=True)[:20],
        "worst_slug_pnl": sorted(by_slug.items(), key=lambda item: item[1])[:20],
        "pnl_by_outcome": dict(by_outcome),
    }


def current_position_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_current = sum(float(row["current_value"]) for row in rows)
    total_initial = sum(float(row["initial_value"]) for row in rows)
    total_cash_pnl = sum(float(row["cash_pnl"]) for row in rows)
    redeemable = [row for row in rows if int(row.get("redeemable") or 0)]
    return {
        "current_positions": len(rows),
        "total_current_value": total_current,
        "total_initial_value": total_initial,
        "total_cash_pnl": total_cash_pnl,
        "roi_on_initial_value": total_cash_pnl / total_initial if total_initial else 0.0,
        "redeemable_positions": len(redeemable),
        "top_current_positions": [
            {
                "condition_id": row["condition_id"],
                "asset_id": row["asset_id"],
                "slug": row.get("slug"),
                "outcome": row.get("outcome"),
                "current_value": row["current_value"],
                "cash_pnl": row["cash_pnl"],
            }
            for row in rows[:20]
        ],
    }


def trade_position_coverage(
    trades: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    closed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    trade_assets = {(row["condition_id"], row["asset_id"]) for row in trades}
    current_assets = {(row["condition_id"], row["asset_id"]) for row in current_rows}
    closed_assets = {(row["condition_id"], row["asset_id"]) for row in closed_rows}
    return {
        "trade_assets": len(trade_assets),
        "trades_with_current_position": len(trade_assets.intersection(current_assets)),
        "trades_with_closed_position": len(trade_assets.intersection(closed_assets)),
        "trades_with_neither": len(trade_assets - current_assets - closed_assets),
    }
