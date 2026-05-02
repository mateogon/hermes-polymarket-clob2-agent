"""Helpers for measuring Polymarket BBO repricing after external moves."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BboSnapshot:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    ts_ms: int


def bbo_changed(before: BboSnapshot, after: BboSnapshot, *, min_change_cents: float = 1.0) -> bool:
    if before.best_ask is None or after.best_ask is None:
        return False
    return abs(after.best_ask - before.best_ask) * 100 >= min_change_cents


def compute_repricing_lag(
    *,
    external_move_ts_ms: int,
    bbo_updates: list[BboSnapshot],
    min_change_cents: float = 1.0,
) -> int | None:
    updates = sorted(
        [snapshot for snapshot in bbo_updates if snapshot.ts_ms >= external_move_ts_ms],
        key=lambda snapshot: snapshot.ts_ms,
    )
    if len(updates) < 2:
        return None
    before = updates[0]
    for after in updates[1:]:
        if bbo_changed(before, after, min_change_cents=min_change_cents):
            return after.ts_ms - external_move_ts_ms
    return None
