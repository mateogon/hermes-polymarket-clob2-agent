"""Market discovery and executable token resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.polymarket.types import MarketMetadata


@dataclass(frozen=True)
class ResolvedMarket:
    condition_id: str
    slug: str
    question: str
    metadata: MarketMetadata
    gamma_reference_prices: tuple[float, ...] = ()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


class MarketData:
    def __init__(self, clob: ClobV2Client, gamma: GammaClient | None = None):
        self.clob = clob
        self.gamma = gamma or GammaClient()

    def resolve_from_gamma(self, query: str) -> ResolvedMarket:
        markets = self.gamma.search_markets(query, limit=1)
        if not markets:
            raise LookupError(f"No Gamma market found for {query!r}")
        market = markets[0]
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
        if not condition_id:
            raise LookupError("Gamma market missing condition ID")
        metadata = self.clob.get_clob_market_info(condition_id)
        prices = tuple(float(x) for x in _json_list(market.get("outcomePrices")) if x is not None)
        return ResolvedMarket(
            condition_id=condition_id,
            slug=str(market.get("slug") or ""),
            question=str(market.get("question") or ""),
            metadata=metadata,
            gamma_reference_prices=prices,
        )

