"""Executable fill simulation against locally recorded L2 books."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.backtest.local_l2_lookup import reconstruct_book_at
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill, simulate_sell_fill
from hermes_polymarket.polymarket.types import FillResult, OrderBook
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class LocalL2Fill:
    available: bool
    reason: str
    token_id: str
    target_ts_ms: int
    fill: FillResult | None = None
    book: OrderBook | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None


def simulate_local_l2_buy(
    db: Database,
    *,
    token_id: str,
    target_ts_ms: int,
    amount_usd: float,
    order_type: str = "fok",
) -> LocalL2Fill:
    state = reconstruct_book_at(db, token_id=token_id, target_ts_ms=target_ts_ms)
    if state is None or token_id not in state.by_token:
        return LocalL2Fill(False, "no_l2_book_at_timestamp", token_id, target_ts_ms)

    book = state.by_token[token_id].as_orderbook()
    fill = simulate_buy_fill(book, amount_usd, order_type=order_type)

    return LocalL2Fill(
        available=fill.filled or fill.is_partial,
        reason=fill.status,
        token_id=token_id,
        target_ts_ms=target_ts_ms,
        fill=fill,
        book=book,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        spread=book.spread,
    )


def simulate_local_l2_sell(
    db: Database,
    *,
    token_id: str,
    target_ts_ms: int,
    shares: float,
    order_type: str = "fok",
) -> LocalL2Fill:
    state = reconstruct_book_at(db, token_id=token_id, target_ts_ms=target_ts_ms)
    if state is None or token_id not in state.by_token:
        return LocalL2Fill(False, "no_l2_book_at_timestamp", token_id, target_ts_ms)

    book = state.by_token[token_id].as_orderbook()
    fill = simulate_sell_fill(book, shares, order_type=order_type)

    return LocalL2Fill(
        available=fill.filled or fill.is_partial,
        reason=fill.status,
        token_id=token_id,
        target_ts_ms=target_ts_ms,
        fill=fill,
        book=book,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        spread=book.spread,
    )
