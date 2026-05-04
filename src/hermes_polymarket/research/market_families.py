"""Research market family classifier.

This module is deliberately semantic: it tells the research loop what model
family a market belongs to before any simulation touches it.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from hermes_polymarket.crypto.crypto_market_classifier import infer_symbol_from_text
from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
from hermes_polymarket.crypto.strike_market import parse_strike_market
from hermes_polymarket.crypto.updown_discovery import UPDOWN_PATTERNS


SUPPORTED_FAMILIES = ("target_hit", "dip_to", "up_down", "above_strike", "below_strike")


@dataclass(frozen=True)
class MarketFamilyClassification:
    family: str
    symbol: str | None
    supported: bool
    fair_value_model: str | None
    reason: str
    target_price: float | None = None
    comparator: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def classify_market_family(text: str, *, current_price: float | None = None) -> MarketFamilyClassification:
    normalized = _normalize(text)
    symbol = infer_symbol_from_text(normalized)
    if symbol is None:
        return MarketFamilyClassification("unsupported", None, False, None, "no_crypto_symbol")

    if any(pattern in normalized for pattern in UPDOWN_PATTERNS) and not _has_explicit_price(normalized):
        return MarketFamilyClassification("up_down", symbol, True, "directional_binary_reference_move", "up_down_text")

    strike = parse_strike_market(normalized)
    if strike is not None:
        return MarketFamilyClassification(
            strike.market_type,
            symbol,
            True,
            "terminal_strike_diffusion",
            "strike_text",
            target_price=strike.strike_price,
            comparator=strike.comparator,
        )

    dip_target = _parse_dip_target(normalized)
    if dip_target is not None:
        return MarketFamilyClassification(
            "dip_to",
            symbol,
            True,
            "barrier_touch_diffusion",
            "dip_target_text",
            target_price=dip_target,
            comparator="below",
        )

    target = parse_multi_strike_target(normalized, current_price=current_price)
    if target is not None:
        family = "dip_to" if _is_dip_text(normalized, target.target_direction) else "target_hit"
        return MarketFamilyClassification(
            family,
            symbol,
            True,
            "barrier_touch_diffusion",
            "target_touch_text",
            target_price=target.target_price,
            comparator=target.target_direction if target.target_direction != "unknown" else None,
        )

    return MarketFamilyClassification("unsupported", symbol, False, None, "unsupported_market_semantics")


def scan_market_families(markets: list[dict[str, Any]], *, current_prices: dict[str, float] | None = None, limit: int = 100) -> dict[str, Any]:
    current_prices = current_prices or {}
    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    for market in markets:
        text = " ".join(str(value or "") for value in (market.get("question") or market.get("title"), market.get("slug")))
        symbol_hint = infer_symbol_from_text(text)
        classification = classify_market_family(text, current_price=current_prices.get(symbol_hint or ""))
        counts[classification.family] += 1
        if not classification.supported:
            rejected[classification.reason] += 1
        row = {
            "slug": market.get("slug"),
            "question": market.get("question") or market.get("title"),
            "condition_id": market.get("conditionId") or market.get("condition_id"),
            "active": bool(market.get("active", False)),
            "closed": bool(market.get("closed", False)),
            **classification.to_dict(),
        }
        if classification.supported:
            candidates.append(row)
    return {
        "mode": "research_market_family_scan",
        "supported_families": list(SUPPORTED_FAMILIES),
        "classified": dict(counts),
        "rejected_by_reason": dict(rejected),
        "candidates": candidates[:limit],
        "total_candidates": len(candidates),
    }


def markets_from_gamma_universe_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    direct = payload.get("markets")
    if isinstance(direct, list):
        markets.extend(row for row in direct if isinstance(row, dict))
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        for market in event.get("markets") or []:
            if isinstance(market, dict):
                row = dict(market)
                row.setdefault("event_slug", event.get("slug"))
                row.setdefault("event_title", event.get("title"))
                markets.append(row)
    return markets


def load_markets_from_file(path: str) -> list[dict[str, Any]]:
    payload = json.loads(open(path).read())
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return markets_from_gamma_universe_payload(payload)
    return []


def _normalize(text: str) -> str:
    return text.lower().replace(",", "").replace("$", "").replace("pt", ".")


def _has_explicit_price(text: str) -> bool:
    return "$" in text or "price" in text or re.search(r"\b\d+(?:\.\d+)?\s*(?:k|m)\b", text) is not None


def _is_dip_text(text: str, target_direction: str) -> bool:
    return target_direction == "below" or any(word in text for word in ("dip", "drop", "fall to", "crash to"))


def _parse_dip_target(text: str) -> float | None:
    match = re.search(r"\b(?:dip|drop|fall|crash)\s+(?:to|under|below)\b[^0-9]*(\d+(?:\.\d+)?)(k|m)?\b", text)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2)
    if suffix == "k":
        value *= 1_000.0
    elif suffix == "m":
        value *= 1_000_000.0
    return value
