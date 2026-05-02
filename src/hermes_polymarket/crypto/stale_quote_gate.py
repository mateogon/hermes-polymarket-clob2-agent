"""Stale quote gate for crypto latency paper signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class StaleQuoteDecision:
    allowed: bool
    reason: str
    external_move_pct: float
    bbo_change_cents: float | None
    best_bid_before: float | None
    best_ask_before: float | None
    best_bid_after: float | None
    best_ask_after: float | None
    stale_window_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None:
        return None
    return float(value)


def evaluate_stale_quote(
    *,
    external_move_pct: float,
    bbo_before: dict[str, Any] | None,
    bbo_after: dict[str, Any] | None,
    max_reprice_cents: float = 1.0,
    max_spread_cents: float = 4.0,
    stale_window_ms: int = 1500,
    require_bbo_before: bool = True,
    require_bbo_after: bool = True,
) -> StaleQuoteDecision:
    if bbo_before is None and require_bbo_before:
        return StaleQuoteDecision(False, "missing_bbo_before", external_move_pct, None, None, None, None, None, stale_window_ms)
    if bbo_after is None and require_bbo_after:
        return StaleQuoteDecision(
            False,
            "missing_bbo_after",
            external_move_pct,
            None,
            _f(bbo_before, "best_bid"),
            _f(bbo_before, "best_ask"),
            None,
            None,
            stale_window_ms,
        )

    before = bbo_before or bbo_after
    after = bbo_after or bbo_before
    bid_before = _f(before, "best_bid")
    ask_before = _f(before, "best_ask")
    bid_after = _f(after, "best_bid")
    ask_after = _f(after, "best_ask")
    spread = None
    if bid_after is not None and ask_after is not None:
        spread = ask_after - bid_after
        if spread * 100.0 > max_spread_cents:
            return StaleQuoteDecision(False, "wide_spread", external_move_pct, None, bid_before, ask_before, bid_after, ask_after, stale_window_ms)

    if ask_before is None or ask_after is None:
        return StaleQuoteDecision(False, "missing_target_ask", external_move_pct, None, bid_before, ask_before, bid_after, ask_after, stale_window_ms)

    bbo_change_cents = abs(ask_after - ask_before) * 100.0
    if bbo_change_cents > max_reprice_cents:
        return StaleQuoteDecision(False, "already_repriced", external_move_pct, bbo_change_cents, bid_before, ask_before, bid_after, ask_after, stale_window_ms)

    return StaleQuoteDecision(True, "stale_quote", external_move_pct, bbo_change_cents, bid_before, ask_before, bid_after, ask_after, stale_window_ms)


def _nearest_bbo_after(db: Database, *, token_id: str, target_ts_ms: int) -> dict[str, Any] | None:
    row = db.conn.execute(
        """
        SELECT * FROM l2_bbo_updates
        WHERE token_id = ? AND received_ts_ms >= ?
        ORDER BY received_ts_ms ASC, id ASC
        LIMIT 1
        """,
        (token_id, target_ts_ms),
    ).fetchone()
    return dict(row) if row else None


def _nearest_bbo_before(db: Database, *, token_id: str, target_ts_ms: int) -> dict[str, Any] | None:
    row = db.conn.execute(
        """
        SELECT * FROM l2_bbo_updates
        WHERE token_id = ? AND received_ts_ms <= ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id, target_ts_ms),
    ).fetchone()
    return dict(row) if row else None


def evaluate_stale_quote_from_l2(
    db: Database,
    *,
    token_id: str,
    external_move_ts_ms: int,
    external_move_pct: float,
    max_reprice_cents: float = 1.0,
    max_spread_cents: float = 4.0,
    stale_window_ms: int = 1500,
) -> StaleQuoteDecision:
    before = _nearest_bbo_before(db, token_id=token_id, target_ts_ms=external_move_ts_ms)
    after = _nearest_bbo_after(db, token_id=token_id, target_ts_ms=external_move_ts_ms + stale_window_ms)
    return evaluate_stale_quote(
        external_move_pct=external_move_pct,
        bbo_before=before,
        bbo_after=after,
        max_reprice_cents=max_reprice_cents,
        max_spread_cents=max_spread_cents,
        stale_window_ms=stale_window_ms,
    )
