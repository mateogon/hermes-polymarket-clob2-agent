"""Market scoring for selecting crypto paper watchlist candidates."""

from __future__ import annotations

from typing import Any

from hermes_polymarket.crypto.market_quality import watchlist_health_report
from hermes_polymarket.storage.db import Database


def _token_score(quality: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if quality.get("best_bid") is not None and quality.get("best_ask") is not None:
        score += 0.20
        reasons.append("two_sided_book")
    spread = quality.get("spread")
    if spread is not None:
        cents = float(spread) * 100.0
        if cents <= 1:
            score += 0.25
            reasons.append("tight_spread")
        elif cents <= 2:
            score += 0.15
            reasons.append("acceptable_spread")
        elif cents > 4:
            score -= 0.25
            reasons.append("wide_spread")
    d2 = float(quality.get("depth_within_2pct_usd") or 0.0)
    d5 = float(quality.get("depth_within_5pct_usd") or 0.0)
    if d2 >= 25:
        score += 0.20
        reasons.append("good_depth_2pct")
    elif d2 >= 10:
        score += 0.10
        reasons.append("some_depth_2pct")
    else:
        score -= 0.20
        reasons.append("thin_depth_2pct")
    if d5 >= 50:
        score += 0.15
        reasons.append("good_depth_5pct")
    elif d5 < 25:
        score -= 0.10
        reasons.append("thin_depth_5pct")
    ask = quality.get("best_ask")
    if ask is not None:
        ask_f = float(ask)
        if 0.10 <= ask_f <= 0.90:
            score += 0.10
            reasons.append("non_extreme_price")
        else:
            score -= 0.20
            reasons.append("extreme_price")
    if quality.get("allowed"):
        score += 0.10
        reasons.append("quality_gate_allowed")
    return max(0.0, min(1.0, score)), reasons


def score_watchlist_markets(db: Database, *, symbol: str | None = None, limit: int = 100) -> dict[str, Any]:
    health = watchlist_health_report(db, symbol=symbol, active_only=True, limit=limit)
    markets: list[dict[str, Any]] = []
    for market in health["markets"]:
        up_score, up_reasons = _token_score(market["up_quality"])
        down_score, down_reasons = _token_score(market["down_quality"])
        score = round((up_score + down_score) / 2.0, 4)
        reasons = sorted(set(up_reasons + down_reasons))
        markets.append(
            {
                "symbol": market["symbol"],
                "slug": market["slug"],
                "condition_id": market["condition_id"],
                "score": score,
                "healthy_tokens": market["healthy_tokens"],
                "recommended_action": "keep_market" if score >= 0.6 and market["healthy_tokens"] >= 2 else "disable_or_replace_market",
                "reasons": reasons,
                "up_quality": market["up_quality"],
                "down_quality": market["down_quality"],
            }
        )
    markets.sort(key=lambda row: row["score"], reverse=True)
    return {"mode": "measurement_paper_only", "data_quality": "local_l2", "markets": markets}


def best_watchlist_markets(db: Database, *, symbol: str | None = None, limit: int = 5) -> dict[str, Any]:
    scored = score_watchlist_markets(db, symbol=symbol, limit=100)
    return {**scored, "markets": scored["markets"][:limit]}
