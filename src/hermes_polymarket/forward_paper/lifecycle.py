"""Lifecycle helpers for forward paper positions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from hermes_polymarket.forward_paper.models import ForwardPaperSignal


@dataclass(frozen=True)
class ForwardPaperPosition:
    position_id: str
    signal_id: str
    run_id: str
    symbol: str
    condition_id: str | None
    token_id: str
    outcome: str
    entry_ts_ms: int
    entry_price: float
    shares: float
    amount_usd: float
    best_bid_at_entry: float | None
    best_ask_at_entry: float | None
    spread_at_entry: float | None
    status: str = "open"
    exit_ts_ms: int | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    data_quality: str = "paper_live"


def open_position_from_signal(signal: ForwardPaperSignal) -> ForwardPaperPosition | None:
    if signal.final_action != "paper_fill":
        return None
    if signal.avg_price is None or signal.shares is None:
        return None

    return ForwardPaperPosition(
        position_id=f"fpp_{uuid4().hex[:12]}",
        signal_id=signal.signal_id,
        run_id=signal.run_id,
        symbol=signal.symbol,
        condition_id=signal.condition_id,
        token_id=signal.token_id,
        outcome=signal.outcome,
        entry_ts_ms=signal.external_move_ts_ms,
        entry_price=signal.avg_price,
        shares=signal.shares,
        amount_usd=signal.amount_usd,
        best_bid_at_entry=signal.best_bid,
        best_ask_at_entry=signal.best_ask,
        spread_at_entry=signal.spread,
        data_quality=signal.data_quality,
    )


def mark_position(
    position: ForwardPaperPosition,
    *,
    mark_price: float,
) -> tuple[float, float, float]:
    unrealized = position.shares * (mark_price - position.entry_price)
    mfe = max(position.max_favorable_excursion, unrealized)
    mae = min(position.max_adverse_excursion, unrealized)
    return unrealized, mfe, mae


def update_excursions(position: ForwardPaperPosition, *, mfe: float, mae: float) -> ForwardPaperPosition:
    return ForwardPaperPosition(**{**position.__dict__, "max_favorable_excursion": mfe, "max_adverse_excursion": mae})


def should_exit_position(
    position: ForwardPaperPosition,
    *,
    mark_price: float,
    ts_ms: int,
    take_profit_cents: float,
    stop_loss_cents: float,
    timeout_seconds: int,
) -> tuple[bool, str]:
    if mark_price >= position.entry_price + take_profit_cents / 100.0:
        return True, "take_profit"
    if mark_price <= position.entry_price - stop_loss_cents / 100.0:
        return True, "stop_loss"
    if ts_ms - position.entry_ts_ms >= timeout_seconds * 1000:
        return True, "timeout"
    return False, "hold"


def close_position(
    position: ForwardPaperPosition,
    *,
    ts_ms: int,
    exit_price: float,
    reason: str,
) -> ForwardPaperPosition:
    pnl = position.shares * (exit_price - position.entry_price)
    return ForwardPaperPosition(
        **{
            **position.__dict__,
            "status": "closed",
            "exit_ts_ms": ts_ms,
            "exit_price": exit_price,
            "exit_reason": reason,
            "gross_pnl": pnl,
            "net_pnl": pnl,
        }
    )
