"""Market quality gates for forward paper crypto experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hermes_polymarket.backtest.local_l2_lookup import reconstruct_book_at
from hermes_polymarket.polymarket.types import OrderBook
from hermes_polymarket.storage.db import Database


@dataclass(frozen=True)
class MarketQualityDecision:
    allowed: bool
    reason: str
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    depth_within_2pct_usd: float
    depth_within_5pct_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def depth_within_pct(book: OrderBook, *, pct: float) -> float:
    best_ask = book.best_ask
    if best_ask is None:
        return 0.0
    max_price = best_ask * (1.0 + pct)
    return sum(level.price * level.size for level in book.asks if level.price <= max_price)


def evaluate_market_quality(
    book: OrderBook,
    *,
    min_best_ask: float = 0.03,
    max_best_ask: float = 0.97,
    min_best_bid: float = 0.01,
    max_spread_cents: float = 4.0,
    min_depth_within_2pct_usd: float = 10.0,
    min_depth_within_5pct_usd: float = 25.0,
) -> MarketQualityDecision:
    best_bid = book.best_bid
    best_ask = book.best_ask
    spread = book.spread
    d2 = depth_within_pct(book, pct=0.02)
    d5 = depth_within_pct(book, pct=0.05)

    if best_ask is None:
        return MarketQualityDecision(False, "no_best_ask", best_bid, best_ask, spread, d2, d5)
    if best_bid is None:
        return MarketQualityDecision(False, "no_best_bid", best_bid, best_ask, spread, d2, d5)
    if best_ask < min_best_ask:
        return MarketQualityDecision(False, "extreme_low_ask", best_bid, best_ask, spread, d2, d5)
    if best_ask > max_best_ask:
        return MarketQualityDecision(False, "extreme_high_ask", best_bid, best_ask, spread, d2, d5)
    if best_bid < min_best_bid:
        return MarketQualityDecision(False, "extreme_low_bid", best_bid, best_ask, spread, d2, d5)
    if spread is not None and spread * 100.0 > max_spread_cents:
        return MarketQualityDecision(False, "wide_spread", best_bid, best_ask, spread, d2, d5)
    if d2 < min_depth_within_2pct_usd:
        return MarketQualityDecision(False, "thin_depth_2pct", best_bid, best_ask, spread, d2, d5)
    if d5 < min_depth_within_5pct_usd:
        return MarketQualityDecision(False, "thin_depth_5pct", best_bid, best_ask, spread, d2, d5)
    return MarketQualityDecision(True, "ok", best_bid, best_ask, spread, d2, d5)


def latest_book_for_token(db: Database, token_id: str) -> OrderBook | None:
    row = db.conn.execute(
        """
        SELECT received_ts_ms
        FROM l2_book_snapshots
        WHERE token_id = ?
        ORDER BY received_ts_ms DESC, id DESC
        LIMIT 1
        """,
        (token_id,),
    ).fetchone()
    if row is None:
        return None
    state = reconstruct_book_at(db, token_id=token_id, target_ts_ms=int(row["received_ts_ms"]))
    if state is None or token_id not in state.by_token:
        return None
    return state.by_token[token_id].as_orderbook()


def token_quality_from_l2(db: Database, token_id: str) -> dict[str, Any]:
    book = latest_book_for_token(db, token_id)
    if book is None:
        return {
            "allowed": False,
            "reason": "no_l2_book",
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "depth_within_2pct_usd": 0.0,
            "depth_within_5pct_usd": 0.0,
        }
    return evaluate_market_quality(book).to_dict()


def watchlist_health_report(db: Database, *, symbol: str | None = None, active_only: bool = True, limit: int = 100) -> dict[str, Any]:
    from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist

    rows = crypto_market_watchlist(db, active_only=active_only, limit=limit)
    if symbol:
        rows = [row for row in rows if str(row.get("symbol") or "").lower() == symbol.lower()]

    markets: list[dict[str, Any]] = []
    for row in rows:
        up_token_id = row.get("up_token_id") or row.get("yes_token_id")
        down_token_id = row.get("down_token_id") or row.get("no_token_id")
        up_quality = token_quality_from_l2(db, str(up_token_id)) if up_token_id else {"allowed": False, "reason": "missing_up_token"}
        down_quality = token_quality_from_l2(db, str(down_token_id)) if down_token_id else {"allowed": False, "reason": "missing_down_token"}
        healthy_tokens = int(bool(up_quality.get("allowed"))) + int(bool(down_quality.get("allowed")))
        recommended_action = "keep_market" if healthy_tokens >= 2 else "disable_or_replace_market"
        markets.append(
            {
                "condition_id": row["condition_id"],
                "slug": row["slug"],
                "symbol": row["symbol"],
                "active": bool(row["active"]),
                "up_token_id": up_token_id,
                "down_token_id": down_token_id,
                "up_quality": up_quality,
                "down_quality": down_quality,
                "healthy_tokens": healthy_tokens,
                "recommended_action": recommended_action,
            }
        )

    return {
        "mode": "measurement_paper_only",
        "data_quality": "local_l2",
        "symbol": symbol,
        "healthy_watchlist_markets": sum(1 for market in markets if market["recommended_action"] == "keep_market"),
        "markets": markets,
    }
