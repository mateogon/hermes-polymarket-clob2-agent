"""Fast historical-approx experiments for multi-strike target markets."""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt
from typing import Any

from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
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


@dataclass(frozen=True)
class MultiStrikeSpotReplayTrade:
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    entry_spot: float
    shares: float
    pnl: float
    roi: float
    edge_at_entry: float
    model_probability: float
    seconds_to_expiry: float
    annualized_vol: float
    fair_value_reason: str
    cost_cents: float = 0.0

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


def replay_yes_trade_path_with_spot(
    trades: list[WalletTrade],
    *,
    token_id: str,
    spot_prices: list[tuple[int, float]],
    target_price: float,
    expiry_ts_ms: int,
    annualized_vol: float,
    edge_threshold: float,
    amount_usd: float,
    hold_seconds: int,
    cost_cents: float = 0.0,
    dynamic_vol_window_seconds: int | None = None,
    min_annualized_vol: float = 0.20,
    max_annualized_vol: float = 2.00,
) -> tuple[list[MultiStrikeSpotReplayTrade], dict[str, Any]]:
    yes_trades = sorted(
        [trade for trade in trades if trade.asset_id == token_id and trade.outcome.lower() == "yes"],
        key=lambda trade: trade.timestamp,
    )
    spots = sorted((int(ts_ms), float(price)) for ts_ms, price in spot_prices if price > 0)
    results: list[MultiStrikeSpotReplayTrade] = []
    evaluated_vols: list[float] = []
    skipped_no_spot = 0
    skipped_no_vol = 0
    skipped_below_edge = 0
    idx = 0
    while idx < len(yes_trades):
        entry = yes_trades[idx]
        spot = price_at_or_before(spots, entry.timestamp * 1000)
        if spot is None:
            skipped_no_spot += 1
            idx += 1
            continue
        selected_vol = annualized_vol
        if dynamic_vol_window_seconds is not None:
            realized = realized_annualized_vol(
                spots,
                entry.timestamp * 1000,
                window_seconds=dynamic_vol_window_seconds,
                min_annualized_vol=min_annualized_vol,
                max_annualized_vol=max_annualized_vol,
            )
            if realized is None:
                skipped_no_vol += 1
                idx += 1
                continue
            selected_vol = realized
        evaluated_vols.append(selected_vol)
        seconds_to_expiry = max(1.0, (expiry_ts_ms - entry.timestamp * 1000) / 1000.0)
        fv = fair_value_target_hit(
            current_price=spot,
            target_price=target_price,
            seconds_to_expiry=seconds_to_expiry,
            annualized_vol=selected_vol,
        )
        effective_entry_price = entry.price + cost_cents / 100.0
        edge = fv.probability_yes - effective_entry_price
        if edge < edge_threshold or effective_entry_price <= 0:
            skipped_below_edge += 1
            idx += 1
            continue
        target_exit_ts = entry.timestamp + hold_seconds
        exit_trade = next((trade for trade in yes_trades[idx + 1 :] if trade.timestamp >= target_exit_ts), None)
        if exit_trade is None and idx + 1 < len(yes_trades):
            exit_trade = yes_trades[-1]
        if exit_trade is None or exit_trade.timestamp <= entry.timestamp:
            idx += 1
            continue
        effective_exit_price = max(0.0, exit_trade.price - cost_cents / 100.0)
        shares = amount_usd / effective_entry_price
        pnl = shares * (effective_exit_price - effective_entry_price)
        results.append(
            MultiStrikeSpotReplayTrade(
                entry_ts=entry.timestamp,
                exit_ts=exit_trade.timestamp,
                entry_price=effective_entry_price,
                exit_price=effective_exit_price,
                entry_spot=spot,
                shares=shares,
                pnl=pnl,
                roi=pnl / amount_usd if amount_usd else 0.0,
                edge_at_entry=edge,
                model_probability=fv.probability_yes,
                seconds_to_expiry=seconds_to_expiry,
                annualized_vol=selected_vol,
                fair_value_reason=fv.reason,
                cost_cents=cost_cents,
            )
        )
        idx = yes_trades.index(exit_trade) + 1

    summary = summarize_spot_replay(
        results,
        observed_yes_trades=len(yes_trades),
        spot_points=len(spots),
        skipped_no_spot=skipped_no_spot,
        skipped_no_vol=skipped_no_vol,
        skipped_below_edge=skipped_below_edge,
        cost_cents=cost_cents,
        vol_mode="realized" if dynamic_vol_window_seconds is not None else "fixed",
        vol_window_seconds=dynamic_vol_window_seconds,
        evaluated_vols=evaluated_vols,
    )
    return results, summary


def realized_annualized_vol(
    spots: list[tuple[int, float]],
    target_ts_ms: int,
    *,
    window_seconds: int,
    min_annualized_vol: float = 0.20,
    max_annualized_vol: float = 2.00,
) -> float | None:
    start_ts_ms = target_ts_ms - window_seconds * 1000
    window = [(ts_ms, price) for ts_ms, price in spots if start_ts_ms <= ts_ms <= target_ts_ms and price > 0]
    if len(window) < 3:
        return None
    returns = [log(window[idx][1] / window[idx - 1][1]) for idx in range(1, len(window)) if window[idx - 1][1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return min_annualized_vol
    avg_step_seconds = max((window[-1][0] - window[0][0]) / 1000.0 / (len(window) - 1), 1.0)
    periods_per_year = 31_536_000 / avg_step_seconds
    annualized = sqrt(variance) * sqrt(periods_per_year)
    return max(min_annualized_vol, min(max_annualized_vol, annualized))


def price_at_or_before(spots: list[tuple[int, float]], target_ts_ms: int) -> float | None:
    best: float | None = None
    for ts_ms, price in spots:
        if ts_ms > target_ts_ms:
            break
        best = price
    return best


def summarize_spot_replay(
    results: list[MultiStrikeSpotReplayTrade],
    *,
    observed_yes_trades: int,
    spot_points: int,
    skipped_no_spot: int,
    skipped_below_edge: int,
    skipped_no_vol: int = 0,
    cost_cents: float = 0.0,
    vol_mode: str = "fixed",
    vol_window_seconds: int | None = None,
    evaluated_vols: list[float] | None = None,
) -> dict[str, Any]:
    pnl = [row.pnl for row in results]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return {
        "data_quality": "historical_spot_fair_value",
        "observed_yes_trades": observed_yes_trades,
        "spot_points": spot_points,
        "simulated_trades": len(results),
        "skipped_no_spot": skipped_no_spot,
        "skipped_no_vol": skipped_no_vol,
        "skipped_below_edge": skipped_below_edge,
        "cost_cents": cost_cents,
        "vol_mode": vol_mode,
        "vol_window_seconds": vol_window_seconds,
        "avg_evaluated_annualized_vol": sum(evaluated_vols) / len(evaluated_vols) if evaluated_vols else None,
        "min_evaluated_annualized_vol": min(evaluated_vols) if evaluated_vols else None,
        "max_evaluated_annualized_vol": max(evaluated_vols) if evaluated_vols else None,
        "avg_annualized_vol": sum(row.annualized_vol for row in results) / len(results) if results else None,
        "min_annualized_vol": min((row.annualized_vol for row in results), default=None),
        "max_annualized_vol": max((row.annualized_vol for row in results), default=None),
        "net_pnl": sum(pnl),
        "win_rate": len(wins) / len(results) if results else 0.0,
        "avg_roi": sum(row.roi for row in results) / len(results) if results else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown": max_drawdown,
    }
