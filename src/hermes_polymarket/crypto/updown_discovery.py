"""Strict Gamma discovery for active crypto up/down markets."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from hermes_polymarket.crypto.crypto_market_classifier import infer_symbol_from_text


UPDOWN_PATTERNS = (
    "up or down",
    "up-or-down",
    "updown",
    "higher or lower",
    "higher-or-lower",
    "rise or fall",
    "rise-or-fall",
)

STRIKE_PATTERNS = (
    "above",
    "below",
    "over",
    "under",
    "hit $",
    "reach $",
)


@dataclass(frozen=True)
class UpDownCandidate:
    event_slug: str
    event_title: str
    question: str
    slug: str
    condition_id: str
    symbol: str
    outcomes: tuple[str, str]
    clob_token_ids: tuple[str, str]
    end_date: str | None
    active: bool
    closed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_slug": self.event_slug,
            "event_title": self.event_title,
            "question": self.question,
            "slug": self.slug,
            "condition_id": self.condition_id,
            "symbol": self.symbol,
            "outcomes": list(self.outcomes),
            "clob_token_ids": list(self.clob_token_ids),
            "end_date": self.end_date,
            "active": self.active,
            "closed": self.closed,
        }


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _text(market: dict[str, Any]) -> str:
    return f"{market.get('question') or market.get('title') or ''} {market.get('slug') or ''}".lower()


def _has_updown_text(text: str) -> bool:
    return any(pattern in text for pattern in UPDOWN_PATTERNS)


def _has_strike_text(text: str) -> bool:
    if any(pattern in text for pattern in STRIKE_PATTERNS):
        return True
    return re.search(r"\b\d+[kmb]?\b", text) is not None and ("price" in text or "$" in text)


def classify_updown_market(
    market: dict[str, Any],
    *,
    event_slug: str = "",
    event_title: str = "",
    allowed_symbols: set[str] | None = None,
) -> tuple[UpDownCandidate | None, str]:
    text = _text(market)
    symbol = infer_symbol_from_text(text)
    if symbol is None:
        return None, "no_crypto_symbol"
    if allowed_symbols is not None and symbol not in allowed_symbols:
        return None, "symbol_not_requested"
    if not bool(market.get("active", False)):
        return None, "inactive"
    if bool(market.get("closed", False)):
        return None, "closed"
    if not _has_updown_text(text):
        return None, "not_updown_text"
    if _has_strike_text(text):
        return None, "strike_market"

    outcomes = tuple(str(item) for item in _coerce_list(market.get("outcomes")) if str(item))
    if len(outcomes) != 2:
        return None, "not_two_outcomes"
    outcome_text = " ".join(outcome.lower() for outcome in outcomes)
    if not (("up" in outcome_text or "higher" in outcome_text or "yes" in outcome_text) and ("down" in outcome_text or "lower" in outcome_text or "no" in outcome_text)):
        return None, "ambiguous_outcomes"

    token_ids = tuple(str(item) for item in _coerce_list(market.get("clobTokenIds") or market.get("clob_token_ids")) if str(item))
    if len(token_ids) != 2:
        return None, "not_two_clob_token_ids"

    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    if not condition_id:
        return None, "missing_condition_id"

    return (
        UpDownCandidate(
            event_slug=event_slug,
            event_title=event_title,
            question=str(market.get("question") or market.get("title") or ""),
            slug=str(market.get("slug") or ""),
            condition_id=condition_id,
            symbol=symbol,
            outcomes=(outcomes[0], outcomes[1]),
            clob_token_ids=(token_ids[0], token_ids[1]),
            end_date=str(market.get("endDate") or "") or None,
            active=bool(market.get("active")),
            closed=bool(market.get("closed")),
        ),
        "accepted",
    )


def discover_updown_from_events(
    events: list[dict[str, Any]],
    *,
    symbols: set[str] | None = None,
) -> dict[str, Any]:
    accepted: dict[str, UpDownCandidate] = {}
    rejected: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()
    candidates_seen = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        event_slug = str(event.get("slug") or "")
        event_title = str(event.get("title") or "")
        markets = event.get("markets") or []
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            candidates_seen += 1
            candidate, reason = classify_updown_market(market, event_slug=event_slug, event_title=event_title, allowed_symbols=symbols)
            if candidate is None:
                reason_counts[reason] += 1
                rejected.append(
                    {
                        "event_slug": event_slug,
                        "slug": str(market.get("slug") or ""),
                        "question": str(market.get("question") or market.get("title") or ""),
                        "reason": reason,
                    }
                )
                continue
            accepted[candidate.condition_id] = candidate

    return {
        "candidates_seen": candidates_seen,
        "discovered": len(accepted),
        "markets": [candidate.to_dict() for candidate in accepted.values()],
        "debug": {
            "rejected_reason_counts": dict(reason_counts),
            "top_rejected": rejected[:50],
        },
    }
