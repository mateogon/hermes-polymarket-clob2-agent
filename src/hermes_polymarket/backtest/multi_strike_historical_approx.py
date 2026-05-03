"""Fast historical-approx experiments for multi-strike target markets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


@dataclass(frozen=True)
class MultiStrikeApproxTrade:
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    roi: float
    edge_at_entry: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def replay_yes_trade_path(
    trades: list[WalletTrade],
    *,
    token_id: str,
    model_probability: float,
    edge_threshold: float,
    amount_usd: float,
    hold_seconds: int,
) -> tuple[list[MultiStrikeApproxTrade], dict[str, Any]]:
    yes_trades = sorted(
        [trade for trade in trades if trade.asset_id == token_id and trade.outcome.lower() == "yes"],
        key=lambda trade: trade.timestamp,
    )
    results: list[MultiStrikeApproxTrade] = []
    idx = 0
    while idx < len(yes_trades):
        entry = yes_trades[idx]
        edge = model_probability - entry.price
        if edge < edge_threshold or entry.price <= 0:
            idx += 1
            continue
        target_exit_ts = entry.timestamp + hold_seconds
        exit_trade = next((trade for trade in yes_trades[idx + 1 :] if trade.timestamp >= target_exit_ts), None)
        if exit_trade is None and idx + 1 < len(yes_trades):
            exit_trade = yes_trades[-1]
        if exit_trade is None or exit_trade.timestamp <= entry.timestamp:
            idx += 1
            continue
        shares = amount_usd / entry.price
        pnl = shares * (exit_trade.price - entry.price)
        results.append(
            MultiStrikeApproxTrade(
                entry_ts=entry.timestamp,
                exit_ts=exit_trade.timestamp,
                entry_price=entry.price,
                exit_price=exit_trade.price,
                shares=shares,
                pnl=pnl,
                roi=pnl / amount_usd if amount_usd else 0.0,
                edge_at_entry=edge,
            )
        )
        idx = yes_trades.index(exit_trade) + 1

    summary = {
        "data_quality": "historical_approx_current_model",
        "observed_yes_trades": len(yes_trades),
        "simulated_trades": len(results),
        "net_pnl": sum(row.pnl for row in results),
        "win_rate": sum(1 for row in results if row.pnl > 0) / len(results) if results else 0.0,
        "avg_roi": sum(row.roi for row in results) / len(results) if results else 0.0,
    }
    return results, summary
