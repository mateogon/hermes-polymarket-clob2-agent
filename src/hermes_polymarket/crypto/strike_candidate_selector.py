"""Dynamic strike market selection for paper-only v2 campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from hermes_polymarket.crypto.market_quality import MarketQualityDecision, evaluate_market_quality
from hermes_polymarket.polymarket.types import OrderBook


@dataclass(frozen=True)
class StrikeRotationConfig:
    min_distance_pct: float = 0.10
    max_distance_pct: float = 2.50
    min_market_score: float = 0.75
    min_best_ask: float = 0.05
    max_best_ask: float = 0.95
    min_depth_within_2pct_usd: float = 10.0
    min_depth_within_5pct_usd: float = 25.0
    require_two_sided_book: bool = True
    reject_extreme: bool = True


@dataclass(frozen=True)
class ScoredStrikeCandidate:
    candidate: dict[str, Any]
    score: float
    recommended: bool
    reasons: tuple[str, ...]
    reject_reasons: tuple[str, ...]
    yes_quality: dict[str, Any] | None
    no_quality: dict[str, Any] | None
    yes_best_ask: float | None
    no_best_ask: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.candidate,
            "rotation_score": self.score,
            "recommended": self.recommended,
            "rotation_reasons": list(self.reasons),
            "reject_reasons": list(self.reject_reasons),
            "yes_quality": self.yes_quality,
            "no_quality": self.no_quality,
            "yes_best_ask": self.yes_best_ask,
            "no_best_ask": self.no_best_ask,
        }


def _end_date_future(end_date: str | None) -> bool:
    if not end_date:
        return False
    try:
        parsed = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)


def _book_quality(book: OrderBook, config: StrikeRotationConfig) -> MarketQualityDecision:
    return evaluate_market_quality(
        book,
        min_best_ask=config.min_best_ask,
        max_best_ask=config.max_best_ask,
        min_depth_within_2pct_usd=config.min_depth_within_2pct_usd,
        min_depth_within_5pct_usd=config.min_depth_within_5pct_usd,
    )


def score_strike_candidate(
    candidate: dict[str, Any],
    *,
    current_price: float,
    yes_book: OrderBook | None,
    no_book: OrderBook | None,
    config: StrikeRotationConfig = StrikeRotationConfig(),
) -> ScoredStrikeCandidate:
    reasons: list[str] = []
    rejects: list[str] = []
    score = 0.0

    strike = candidate.get("strike_price")
    distance_pct = None
    if strike:
        distance_pct = abs((current_price - float(strike)) / float(strike) * 100.0)
        if config.min_distance_pct <= distance_pct <= config.max_distance_pct:
            distance_span = max(config.max_distance_pct - config.min_distance_pct, 1e-9)
            score += 0.25 * (1.0 - min((distance_pct - config.min_distance_pct) / distance_span, 1.0))
            reasons.append("near_atm")
        else:
            rejects.append("outside_distance")
    else:
        rejects.append("missing_strike_price")

    market_score = float(candidate.get("score") or candidate.get("market_score") or 0.0)
    if market_score >= config.min_market_score:
        score += 0.15
        reasons.append("market_score_ok")
    else:
        rejects.append("market_score_below_threshold")

    yes_quality = _book_quality(yes_book, config).to_dict() if yes_book is not None else None
    no_quality = _book_quality(no_book, config).to_dict() if no_book is not None else None
    if yes_quality is None or no_quality is None:
        rejects.append("missing_rest_book")
    else:
        if yes_quality.get("best_bid") is not None and yes_quality.get("best_ask") is not None and no_quality.get("best_bid") is not None and no_quality.get("best_ask") is not None:
            score += 0.15
            reasons.append("two_sided_book")
        elif config.require_two_sided_book:
            rejects.append("one_sided_book")

        asks = [float(value) for value in (yes_quality.get("best_ask"), no_quality.get("best_ask")) if value is not None]
        if asks and all(config.min_best_ask <= ask <= config.max_best_ask for ask in asks):
            score += 0.20
            reasons.append("non_extreme_price")
        elif config.reject_extreme:
            rejects.append("extreme_price")

        spreads = [value for value in (yes_quality.get("spread"), no_quality.get("spread")) if value is not None]
        if spreads and all(float(spread) * 100.0 <= 2.0 for spread in spreads):
            score += 0.15
            reasons.append("tight_spread")
        elif spreads:
            rejects.append("wide_spread")

        d2 = min(float(yes_quality.get("depth_within_2pct_usd") or 0.0), float(no_quality.get("depth_within_2pct_usd") or 0.0))
        d5 = min(float(yes_quality.get("depth_within_5pct_usd") or 0.0), float(no_quality.get("depth_within_5pct_usd") or 0.0))
        if d2 >= config.min_depth_within_2pct_usd:
            score += 0.12
            reasons.append("good_depth_2pct")
        else:
            rejects.append("thin_depth_2pct")
        if d5 >= config.min_depth_within_5pct_usd:
            score += 0.08
            reasons.append("good_depth_5pct")
        else:
            rejects.append("thin_depth_5pct")

        if bool(yes_quality.get("allowed")) and bool(no_quality.get("allowed")):
            score += 0.05
            reasons.append("quality_gate_allowed")
        else:
            for quality in (yes_quality, no_quality):
                reason = quality.get("reason")
                if reason and reason != "ok":
                    rejects.append(str(reason))

    if _end_date_future(candidate.get("end_date")):
        score += 0.05
        reasons.append("future_end_date")
    else:
        rejects.append("expired_or_missing_end_date")

    unique_rejects = tuple(sorted(set(rejects)))
    final_score = round(min(score, 1.0), 4)
    return ScoredStrikeCandidate(
        candidate={**candidate, "current_price": current_price, "distance_pct": ((current_price - float(strike)) / float(strike) * 100.0) if strike else None},
        score=final_score,
        recommended=not unique_rejects and final_score >= config.min_market_score,
        reasons=tuple(sorted(set(reasons))),
        reject_reasons=unique_rejects,
        yes_quality=yes_quality,
        no_quality=no_quality,
        yes_best_ask=float(yes_quality["best_ask"]) if yes_quality and yes_quality.get("best_ask") is not None else None,
        no_best_ask=float(no_quality["best_ask"]) if no_quality and no_quality.get("best_ask") is not None else None,
    )
