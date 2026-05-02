"""Signal-only wallet-flow copyability checks."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.data_sources.wallet_registry import WalletConfig
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.polymarket.types import OrderBook
from hermes_polymarket.signals.base import Signal


@dataclass(frozen=True)
class CopyabilityDecision:
    copyable: bool
    reason: str
    leader_price: float
    our_avg_price: float = 0.0
    worse_by_cents: float = 0.0
    latency_seconds: float | None = None
    paper_amount_usd: float = 0.0


def evaluate_copyability(
    trade: WalletTrade,
    book: OrderBook,
    wallet: WalletConfig,
    *,
    now_ts: int,
    paper_amount_usd: float = 5.0,
) -> CopyabilityDecision:
    if trade.notional_usd < wallet.min_trade_size_usd:
        return CopyabilityDecision(False, "leader_trade_too_small", trade.price, paper_amount_usd=paper_amount_usd)

    delay = now_ts - trade.timestamp
    if delay < 0:
        return CopyabilityDecision(False, "wallet_trade_from_future", trade.price, latency_seconds=delay, paper_amount_usd=paper_amount_usd)
    if delay > wallet.max_copy_delay_seconds:
        return CopyabilityDecision(False, "stale_wallet_trade", trade.price, latency_seconds=delay, paper_amount_usd=paper_amount_usd)

    if trade.side.upper() != "BUY":
        return CopyabilityDecision(False, "only_buy_copy_supported_v1", trade.price, latency_seconds=delay, paper_amount_usd=paper_amount_usd)

    fill = simulate_buy_fill(book, paper_amount_usd, order_type="fok")
    if not fill.filled:
        return CopyabilityDecision(False, f"not_executable:{fill.status}", trade.price, latency_seconds=delay, paper_amount_usd=paper_amount_usd)

    worse = (fill.avg_price - trade.price) * 100.0
    if worse > wallet.max_entry_worse_cents:
        return CopyabilityDecision(
            False,
            "entry_too_late_or_too_expensive",
            trade.price,
            fill.avg_price,
            worse,
            delay,
            paper_amount_usd,
        )

    return CopyabilityDecision(True, "copyable_for_paper", trade.price, fill.avg_price, worse, delay, paper_amount_usd)


def wallet_trade_to_signal(trade: WalletTrade, decision: CopyabilityDecision, *, wallet_score: float) -> Signal | None:
    if not decision.copyable:
        return None

    bounded_score = min(1.0, max(0.0, wallet_score))
    model_probability = min(0.65, max(0.52, 0.50 + bounded_score * 0.10))
    confidence = min(0.45, max(0.10, 0.15 + bounded_score * 0.20))
    return Signal(
        market_id=trade.condition_id,
        outcome=trade.outcome,
        model_probability=model_probability,
        confidence=confidence,
        reason=(
            f"Wallet-flow signal: {trade.wallet} bought {trade.outcome} at {trade.price:.3f}; "
            f"paper entry {decision.our_avg_price:.3f}; "
            f"worse_by={decision.worse_by_cents:.2f}c; delay={decision.latency_seconds}s"
        ),
        sources=("polymarket_data_api", "wallet_flow"),
    )

