"""Wallet-flow historical replay.

The first replay mode is deliberately approximate: it uses public wallet trades
as price observations and labels output with `historical_approx`.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict

from hermes_polymarket.backtest.exit_models import ExitResult, leader_exit, pnl_for_exit
from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayRunConfig, ReplayTradeResult
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade


def replay_wallet_trades(
    trades: list[WalletTrade],
    config: ReplayRunConfig,
    *,
    run_id: str | None = None,
    categories: dict[str, str] | None = None,
) -> tuple[str, list[ReplayTradeResult], dict]:
    run_id = run_id or f"wallet_replay_{uuid.uuid4().hex[:12]}"
    categories = categories or {}
    ordered = sorted(trades, key=lambda trade: trade.timestamp)
    entries = [trade for trade in ordered if trade.wallet.lower() == config.wallet.lower() and trade.side.upper() == "BUY"]
    results: list[ReplayTradeResult] = []
    for entry in entries:
        for delay in config.delays_seconds:
            results.append(_replay_entry(entry, ordered, config, run_id, delay, categories.get(entry.condition_id)))
    return run_id, results, summarize_replay(results, config.data_quality)


def _replay_entry(
    entry: WalletTrade,
    trades: list[WalletTrade],
    config: ReplayRunConfig,
    run_id: str,
    delay: int,
    category: str | None,
) -> ReplayTradeResult:
    replay_id = f"{run_id}:{entry.tx_hash or entry.timestamp}:{delay}"
    delayed_price = _price_at_or_after(trades, entry, entry.timestamp + delay)
    if delayed_price is None:
        return _skipped(replay_id, run_id, entry, config, delay, category, "no_price_at_delay")
    worse = (delayed_price - entry.price) * 100.0
    if delay > config.max_delay_seconds:
        return _skipped(replay_id, run_id, entry, config, delay, category, "stale_delay")
    if worse > config.max_worse_entry_cents:
        return _skipped(replay_id, run_id, entry, config, delay, category, "entry_too_late_or_too_expensive", delayed_price, worse)

    exit_result = _exit_for_entry(entry, trades, config)
    if exit_result.status != "closed" or exit_result.exit_price is None:
        return ReplayTradeResult(
            replay_trade_id=replay_id,
            run_id=run_id,
            wallet=entry.wallet,
            condition_id=entry.condition_id,
            asset_id=entry.asset_id,
            outcome=entry.outcome,
            delay_seconds=delay,
            exit_model=config.exit_model,
            status="pending",
            entry_time=entry.timestamp + delay,
            entry_price=delayed_price,
            leader_entry_price=entry.price,
            worse_entry_cents=worse,
            category=category,
            payload={"data_quality": config.data_quality, "pending_reason": exit_result.reason},
        )

    pnl, roi = pnl_for_exit(entry_price=delayed_price, exit_price=exit_result.exit_price, amount_usd=config.paper_amount_usd)
    return ReplayTradeResult(
        replay_trade_id=replay_id,
        run_id=run_id,
        wallet=entry.wallet,
        condition_id=entry.condition_id,
        asset_id=entry.asset_id,
        outcome=entry.outcome,
        delay_seconds=delay,
        exit_model=config.exit_model,
        status="closed",
        entry_time=entry.timestamp + delay,
        entry_price=delayed_price,
        leader_entry_price=entry.price,
        exit_time=exit_result.exit_time,
        exit_price=exit_result.exit_price,
        pnl=pnl,
        roi=roi,
        worse_entry_cents=worse,
        category=category,
        payload={"data_quality": config.data_quality, "exit_reason": exit_result.reason},
    )


def _exit_for_entry(entry: WalletTrade, trades: list[WalletTrade], config: ReplayRunConfig) -> ExitResult:
    if config.exit_model == ExitModel.LEADER_EXIT:
        return leader_exit(entry, trades)
    if config.exit_model == ExitModel.RESOLUTION_EXIT:
        # Historical replay does not have trusted resolution data yet. Keep this
        # explicit so reports do not imply resolution PnL was computed.
        return ExitResult(ExitModel.RESOLUTION_EXIT, "pending", reason="resolution_data_missing")
    if config.exit_model == ExitModel.RISK_EXIT:
        # Risk exit requires a local L2/price path. Data API trades alone are
        # not a reliable path for TP/SL/timeout replay.
        return ExitResult(ExitModel.RISK_EXIT, "pending", reason="price_path_missing")
    raise ValueError(f"Unsupported exit model: {config.exit_model}")


def _price_at_or_after(trades: list[WalletTrade], entry: WalletTrade, ts: int) -> float | None:
    candidates = [
        trade
        for trade in trades
        if trade.condition_id == entry.condition_id
        and trade.asset_id == entry.asset_id
        and trade.timestamp >= ts
        and trade.side.upper() == "BUY"
    ]
    if not candidates:
        return entry.price if ts == entry.timestamp else None
    return sorted(candidates, key=lambda trade: trade.timestamp)[0].price


def _skipped(
    replay_id: str,
    run_id: str,
    entry: WalletTrade,
    config: ReplayRunConfig,
    delay: int,
    category: str | None,
    reason: str,
    entry_price: float | None = None,
    worse: float | None = None,
) -> ReplayTradeResult:
    return ReplayTradeResult(
        replay_trade_id=replay_id,
        run_id=run_id,
        wallet=entry.wallet,
        condition_id=entry.condition_id,
        asset_id=entry.asset_id,
        outcome=entry.outcome,
        delay_seconds=delay,
        exit_model=config.exit_model,
        status="skipped",
        entry_time=entry.timestamp + delay,
        entry_price=entry_price,
        leader_entry_price=entry.price,
        worse_entry_cents=worse,
        skipped_reason=reason,
        category=category,
        payload={"data_quality": config.data_quality},
    )


def summarize_replay(results: list[ReplayTradeResult], data_quality: str) -> dict:
    by_delay: dict[int, list[ReplayTradeResult]] = defaultdict(list)
    skipped = Counter()
    category_pnl: dict[str, float] = defaultdict(float)
    pending = 0
    for result in results:
        by_delay[result.delay_seconds].append(result)
        if result.status == "skipped":
            skipped[result.skipped_reason or "unknown"] += 1
        if result.status == "pending":
            pending += 1
        if result.category and result.pnl is not None:
            category_pnl[result.category] += result.pnl

    delays = {}
    for delay, rows in sorted(by_delay.items()):
        closed = [row for row in rows if row.status == "closed" and row.pnl is not None]
        delays[str(delay)] = {
            "observed": len(rows),
            "replayed": len(closed),
            "skipped": sum(1 for row in rows if row.status == "skipped"),
            "pending": sum(1 for row in rows if row.status == "pending"),
            "roi": sum(row.roi or 0.0 for row in closed) / len(closed) if closed else 0.0,
            "win_rate": sum(1 for row in closed if (row.pnl or 0) > 0) / len(closed) if closed else 0.0,
            "max_drawdown": _max_drawdown([row.pnl or 0.0 for row in closed]),
            "average_worse_entry_cents": _average([row.worse_entry_cents for row in rows if row.worse_entry_cents is not None]),
        }
    return {
        "data_quality": data_quality,
        "data_quality_notes": [
            "entry prices are approximated from public wallet trades, not L2 orderbook",
            "slippage is not reliable until local_l2 mode",
            "PnL is only meaningful for leader_exit when sell observed",
        ],
        "observed_trades": len(results),
        "replayed_trades": sum(1 for row in results if row.status == "closed"),
        "pending_trades": pending,
        "skipped_trades_by_reason": dict(skipped),
        "by_delay": delays,
        "pnl_by_category": dict(category_pnl),
        "best_category": max(category_pnl, key=category_pnl.get) if category_pnl else None,
        "worst_category": min(category_pnl, key=category_pnl.get) if category_pnl else None,
    }


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)
