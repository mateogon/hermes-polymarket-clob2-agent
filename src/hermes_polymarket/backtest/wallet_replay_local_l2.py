"""Wallet-flow replay using locally recorded executable L2 books."""

from __future__ import annotations

from hermes_polymarket.backtest.exit_models import leader_exit, pnl_for_exit
from hermes_polymarket.backtest.local_l2_execution import simulate_local_l2_buy
from hermes_polymarket.backtest.wallet_replay import summarize_replay
from hermes_polymarket.backtest.wallet_replay_models import ReplayRunConfig, ReplayTradeResult
from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.storage.db import Database


def replay_wallet_trades_local_l2(
    db: Database,
    trades: list[WalletTrade],
    config: ReplayRunConfig,
    *,
    run_id: str,
    categories: dict[str, str] | None = None,
) -> list[ReplayTradeResult]:
    categories = categories or {}
    ordered = sorted(trades, key=lambda trade: trade.timestamp)
    entries = [trade for trade in ordered if trade.wallet.lower() == config.wallet.lower() and trade.side.upper() == "BUY"]
    results: list[ReplayTradeResult] = []

    for entry in entries:
        for delay in config.delays_seconds:
            target_ts_ms = (entry.timestamp + delay) * 1000
            local_fill = simulate_local_l2_buy(
                db,
                token_id=entry.asset_id,
                target_ts_ms=target_ts_ms,
                amount_usd=config.paper_amount_usd,
                order_type="fok",
            )
            replay_id = f"{run_id}:{entry.tx_hash or entry.timestamp}:{delay}:local_l2"
            category = categories.get(entry.condition_id)
            payload = {
                "data_quality": "local_l2",
                "target_ts_ms": target_ts_ms,
                "best_bid": local_fill.best_bid,
                "best_ask": local_fill.best_ask,
                "spread": local_fill.spread,
            }

            if not local_fill.available or local_fill.fill is None:
                results.append(
                    ReplayTradeResult(
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
                        leader_entry_price=entry.price,
                        skipped_reason=local_fill.reason,
                        category=category,
                        payload=payload,
                    )
                )
                continue

            entry_price = local_fill.fill.avg_price
            worse_entry_cents = (entry_price - entry.price) * 100.0
            exit_result = leader_exit(entry, ordered)
            if exit_result.status != "closed" or exit_result.exit_price is None:
                results.append(
                    ReplayTradeResult(
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
                        entry_price=entry_price,
                        leader_entry_price=entry.price,
                        worse_entry_cents=worse_entry_cents,
                        category=category,
                        payload={**payload, "pending_reason": exit_result.reason},
                    )
                )
                continue

            pnl, roi = pnl_for_exit(entry_price=entry_price, exit_price=exit_result.exit_price, amount_usd=config.paper_amount_usd)
            results.append(
                ReplayTradeResult(
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
                    entry_price=entry_price,
                    leader_entry_price=entry.price,
                    exit_time=exit_result.exit_time,
                    exit_price=exit_result.exit_price,
                    pnl=pnl,
                    roi=roi,
                    worse_entry_cents=worse_entry_cents,
                    category=category,
                    payload={**payload, "exit_reason": exit_result.reason},
                )
            )

    return results


def summarize_local_l2_replay(results: list[ReplayTradeResult]) -> dict:
    summary = summarize_replay(results, "local_l2")
    summary["data_quality_notes"] = [
        "entry prices use locally recorded executable L2 orderbooks",
        "coverage is limited to timestamps where local L2 snapshots exist",
        "exit PnL is only meaningful for leader_exit when sell observed",
    ]
    summary["local_l2_coverage"] = {
        "entries_with_l2": sum(1 for row in results if row.entry_price is not None),
        "entries_without_l2": sum(1 for row in results if row.skipped_reason == "no_l2_book_at_timestamp"),
        "no_l2_book_at_timestamp": sum(1 for row in results if row.skipped_reason == "no_l2_book_at_timestamp"),
    }
    return summary
