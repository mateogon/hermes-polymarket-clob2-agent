"""Parsing helpers for crypto strike markets."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StrikeMarketInfo:
    market_type: str
    comparator: str
    strike_price: float


def parse_strike_market(text: str) -> StrikeMarketInfo | None:
    normalized = text.lower().replace(",", "").replace("$", "")
    match = re.search(r"\b(above|below|over|under)\b[^0-9]*(\d+(?:\.\d+)?)(k)?\b", normalized)
    if not match:
        return None

    word = match.group(1)
    comparator = "above" if word in {"above", "over"} else "below"
    strike = float(match.group(2))
    if match.group(3) == "k":
        strike *= 1000

    return StrikeMarketInfo(
        market_type=f"{comparator}_strike",
        comparator=comparator,
        strike_price=strike,
    )
