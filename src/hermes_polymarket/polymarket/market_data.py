"""Market discovery and executable token resolution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.polymarket.types import MarketMetadata, OrderBook, TokenInfo


CONDITION_ID_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
TOKEN_ID_RE = re.compile(r"^[0-9]{20,}$")


class MarketIdentifierType(str, Enum):
    SLUG = "slug"
    CONDITION_ID = "condition_id"
    TOKEN_ID = "token_id"
    SEARCH = "search"


@dataclass(frozen=True)
class ResolvedMarket:
    condition_id: str
    slug: str
    question: str
    metadata: MarketMetadata
    gamma_market: dict[str, Any]
    selected_token: TokenInfo | None = None
    gamma_reference_prices: tuple[float, ...] = ()


@dataclass(frozen=True)
class ResolvedOrderBook:
    market: ResolvedMarket
    token: TokenInfo
    book: OrderBook


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _condition_id(market: dict[str, Any]) -> str:
    return str(market.get("conditionId") or market.get("condition_id") or "")


def _is_tradeable_clob_market(market: dict[str, Any]) -> bool:
    token_ids = _json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    return (
        bool(_condition_id(market))
        and bool(token_ids)
        and bool(market.get("active", True))
        and not bool(market.get("closed", False))
    )


def _outcomes(market: dict[str, Any]) -> list[str]:
    return [str(x) for x in _json_list(market.get("outcomes"))]


def _prices(market: dict[str, Any]) -> tuple[float, ...]:
    values: list[float] = []
    for raw in _json_list(market.get("outcomePrices")):
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return tuple(values)


def _identifier_type(value: str, explicit: MarketIdentifierType | str | None) -> MarketIdentifierType:
    if explicit is not None:
        return MarketIdentifierType(explicit)
    cleaned = value.strip()
    if CONDITION_ID_RE.match(cleaned):
        return MarketIdentifierType.CONDITION_ID
    if TOKEN_ID_RE.match(cleaned):
        return MarketIdentifierType.TOKEN_ID
    if " " in cleaned:
        return MarketIdentifierType.SEARCH
    return MarketIdentifierType.SLUG


class MarketData:
    def __init__(self, clob: ClobV2Client, gamma: GammaClient | None = None):
        self.clob = clob
        self.gamma = gamma or GammaClient()

    def resolve_from_gamma(self, query: str) -> ResolvedMarket:
        return self.resolve_market(query, identifier_type=MarketIdentifierType.SEARCH)

    def resolve_market(
        self,
        identifier: str,
        *,
        identifier_type: MarketIdentifierType | str | None = None,
        outcome: str | None = None,
    ) -> ResolvedMarket:
        id_type = _identifier_type(identifier, identifier_type)
        markets = self._candidate_markets(identifier, id_type)
        if not markets:
            raise LookupError(f"No Gamma market found for {identifier!r}")

        market = self._single_market(identifier, id_type, markets)
        if not _is_tradeable_clob_market(market):
            raise ValueError("Resolved market is closed, inactive, or missing CLOB token IDs")

        condition_id = _condition_id(market)
        if not condition_id:
            raise LookupError("Gamma market missing condition ID")
        metadata = self.clob.get_clob_market_info(condition_id)
        selected = self._selected_token(metadata, market, id_type, identifier, outcome)
        return ResolvedMarket(
            condition_id=condition_id,
            slug=str(market.get("slug") or ""),
            question=str(market.get("question") or ""),
            metadata=metadata,
            gamma_market=market,
            selected_token=selected,
            gamma_reference_prices=_prices(market),
        )

    def resolve_orderbook(
        self,
        identifier: str,
        *,
        outcome: str | None = None,
        identifier_type: MarketIdentifierType | str | None = None,
    ) -> ResolvedOrderBook:
        market = self.resolve_market(identifier, identifier_type=identifier_type, outcome=outcome)
        token = market.selected_token
        if token is None:
            if outcome is None:
                raise LookupError("Outcome is required when identifier is not a token ID")
            token = market.metadata.token_for_outcome(outcome)
        return ResolvedOrderBook(market=market, token=token, book=self.clob.get_orderbook(token.token_id))

    def _candidate_markets(self, identifier: str, id_type: MarketIdentifierType) -> list[dict[str, Any]]:
        if id_type == MarketIdentifierType.SLUG:
            return self.gamma.markets_by_slug(identifier)
        if id_type == MarketIdentifierType.CONDITION_ID:
            return self.gamma.markets_by_condition_id(identifier)
        if id_type == MarketIdentifierType.TOKEN_ID:
            return self.gamma.markets_by_token_id(identifier)
        return self.gamma.search_markets(identifier, limit=10)

    def _single_market(self, identifier: str, id_type: MarketIdentifierType, markets: list[dict[str, Any]]) -> dict[str, Any]:
        if id_type == MarketIdentifierType.SLUG:
            matches = [m for m in markets if str(m.get("slug") or "") == identifier]
        elif id_type == MarketIdentifierType.CONDITION_ID:
            matches = [m for m in markets if _condition_id(m).lower() == identifier.lower()]
        elif id_type == MarketIdentifierType.TOKEN_ID:
            matches = [m for m in markets if identifier in {str(x) for x in _json_list(m.get("clobTokenIds") or m.get("clob_token_ids"))}]
        else:
            matches = markets
        if not matches:
            raise LookupError(f"No exact market match for {identifier!r}")
        if len(matches) > 1:
            labels = ", ".join(str(m.get("slug") or m.get("question") or _condition_id(m)) for m in matches[:5])
            raise LookupError(f"Ambiguous market identifier {identifier!r}: {labels}")
        return matches[0]

    def _selected_token(
        self,
        metadata: MarketMetadata,
        market: dict[str, Any],
        id_type: MarketIdentifierType,
        identifier: str,
        outcome: str | None,
    ) -> TokenInfo | None:
        if id_type == MarketIdentifierType.TOKEN_ID:
            for token in metadata.tokens:
                if token.token_id == identifier:
                    return token
            token_ids = [str(x) for x in _json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))]
            outcomes = _outcomes(market)
            for index, token_id in enumerate(token_ids):
                if token_id == identifier:
                    label = outcomes[index] if index < len(outcomes) else f"outcome_{index}"
                    return TokenInfo(token_id=identifier, outcome=label)
            raise LookupError("Token ID is not part of resolved market")
        if outcome is None:
            return None
        return metadata.token_for_outcome(outcome)
