"""Exit models for wallet replay."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.backtest.wallet_replay_models import ExitModel


@dataclass(frozen=True)
class ExitResult:
    exit_model: ExitModel
    status: str
    exit_time: int | None = None
    exit_price: float | None = None
    reason: str = ""


def leader_exit(entry: WalletTrade, later_trades: list[WalletTrade]) -> ExitResult:
    for trade in sorted(later_trades, key=lambda t: t.timestamp):
        if (
            trade.timestamp > entry.timestamp
            and trade.wallet.lower() == entry.wallet.lower()
            and trade.condition_id == entry.condition_id
            and trade.asset_id == entry.asset_id
            and trade.side.upper() == "SELL"
        ):
            return ExitResult(ExitModel.LEADER_EXIT, "closed", trade.timestamp, trade.price, "leader_sell")
    return ExitResult(ExitModel.LEADER_EXIT, "pending", reason="leader_exit_not_observed")


def resolution_exit(*, resolved_outcome: str | None, entry_outcome: str, resolved_ts: int | None = None) -> ExitResult:
    if resolved_outcome is None:
        return ExitResult(ExitModel.RESOLUTION_EXIT, "pending", reason="market_unresolved")
    payout = 1.0 if resolved_outcome.strip().lower() == entry_outcome.strip().lower() else 0.0
    return ExitResult(ExitModel.RESOLUTION_EXIT, "closed", resolved_ts, payout, "resolution")


def risk_exit(
    *,
    entry_ts: int,
    entry_price: float,
    price_path: list[tuple[int, float]],
    take_profit_cents: float = 10.0,
    stop_loss_cents: float = 5.0,
    timeout_seconds: int = 900,
) -> ExitResult:
    tp = entry_price + take_profit_cents / 100.0
    sl = entry_price - stop_loss_cents / 100.0
    deadline = entry_ts + timeout_seconds
    for ts, price in sorted(price_path):
        if ts <= entry_ts:
            continue
        if price >= tp:
            return ExitResult(ExitModel.RISK_EXIT, "closed", ts, price, "take_profit")
        if price <= sl:
            return ExitResult(ExitModel.RISK_EXIT, "closed", ts, price, "stop_loss")
        if ts >= deadline:
            return ExitResult(ExitModel.RISK_EXIT, "closed", ts, price, "timeout")
    return ExitResult(ExitModel.RISK_EXIT, "pending", reason="risk_exit_not_observed")


def pnl_for_exit(*, entry_price: float, exit_price: float, amount_usd: float) -> tuple[float, float]:
    shares = amount_usd / entry_price
    pnl = shares * (exit_price - entry_price)
    return pnl, pnl / amount_usd if amount_usd else 0.0

