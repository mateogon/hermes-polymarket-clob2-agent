"""Parsing helpers for long-dated crypto multi-strike target markets."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MultiStrikeTargetInfo:
    market_type: str
    target_price: float
    target_direction: str


def _normalize_price_text(text: str) -> str:
    return text.lower().replace(",", "").replace("$", "").replace("pt", ".")


def _parse_price(raw: str, suffix: str | None) -> float:
    value = float(raw)
    if suffix == "k":
        value *= 1_000.0
    elif suffix == "m":
        value *= 1_000_000.0
    return value


def parse_multi_strike_target(text: str, *, current_price: float | None = None) -> MultiStrikeTargetInfo | None:
    normalized = _normalize_price_text(text)
    if not re.search(r"\b(hit|reach|touch|dip|drop|fall)\b", normalized):
        return None

    # Prefer explicit downside phrasing before generic event titles like
    # "What price will Ethereum hit in 2026?", otherwise the year can be
    # misparsed as the target for "dip to 800" markets.
    match = re.search(r"\b(?:dip|drop|fall)\s+to\b[^0-9]*(\d+(?:\.\d+)?)(k|m)?\b", normalized)
    if not match:
        match = re.search(r"\b(?:hit|reach|touch)\b[^0-9]*(\d+(?:\.\d+)?)(k|m)?\b", normalized)
    if not match:
        return None

    target = _parse_price(match.group(1), match.group(2))
    direction = "unknown"
    if current_price is not None and current_price > 0:
        direction = "above" if target >= current_price else "below"

    return MultiStrikeTargetInfo(
        market_type="multi_strike_event",
        target_price=target,
        target_direction=direction,
    )
