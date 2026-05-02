"""Public Polymarket Data API positions client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DATA_API = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class CurrentPosition:
    wallet: str
    asset_id: str
    condition_id: str
    size: float
    avg_price: float
    initial_value: float
    current_value: float
    cash_pnl: float
    percent_pnl: float
    total_bought: float
    realized_pnl: float
    cur_price: float
    redeemable: bool
    mergeable: bool
    title: str
    slug: str
    event_slug: str
    outcome: str
    outcome_index: int | None
    opposite_outcome: str
    opposite_asset: str
    end_date: str
    negative_risk: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class ClosedPosition:
    wallet: str
    asset_id: str
    condition_id: str
    avg_price: float
    total_bought: float
    realized_pnl: float
    cur_price: float
    timestamp: int
    title: str
    slug: str
    event_slug: str
    outcome: str
    outcome_index: int | None
    opposite_outcome: str
    opposite_asset: str
    end_date: str
    raw: dict[str, Any]


def _f(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _i(row: dict[str, Any], key: str) -> int | None:
    try:
        value = row.get(key)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_current_position(row: Any) -> CurrentPosition | None:
    if not isinstance(row, dict):
        return None
    try:
        return CurrentPosition(
            wallet=str(row["proxyWallet"]),
            asset_id=str(row["asset"]),
            condition_id=str(row["conditionId"]),
            size=_f(row, "size"),
            avg_price=_f(row, "avgPrice"),
            initial_value=_f(row, "initialValue"),
            current_value=_f(row, "currentValue"),
            cash_pnl=_f(row, "cashPnl"),
            percent_pnl=_f(row, "percentPnl"),
            total_bought=_f(row, "totalBought"),
            realized_pnl=_f(row, "realizedPnl"),
            cur_price=_f(row, "curPrice"),
            redeemable=bool(row.get("redeemable")),
            mergeable=bool(row.get("mergeable")),
            title=str(row.get("title") or ""),
            slug=str(row.get("slug") or ""),
            event_slug=str(row.get("eventSlug") or ""),
            outcome=str(row.get("outcome") or ""),
            outcome_index=_i(row, "outcomeIndex"),
            opposite_outcome=str(row.get("oppositeOutcome") or ""),
            opposite_asset=str(row.get("oppositeAsset") or ""),
            end_date=str(row.get("endDate") or ""),
            negative_risk=bool(row.get("negativeRisk")),
            raw=row,
        )
    except (KeyError, TypeError, ValueError):
        return None


def parse_closed_position(row: Any) -> ClosedPosition | None:
    if not isinstance(row, dict):
        return None
    try:
        return ClosedPosition(
            wallet=str(row["proxyWallet"]),
            asset_id=str(row["asset"]),
            condition_id=str(row["conditionId"]),
            avg_price=_f(row, "avgPrice"),
            total_bought=_f(row, "totalBought"),
            realized_pnl=_f(row, "realizedPnl"),
            cur_price=_f(row, "curPrice"),
            timestamp=int(row.get("timestamp") or 0),
            title=str(row.get("title") or ""),
            slug=str(row.get("slug") or ""),
            event_slug=str(row.get("eventSlug") or ""),
            outcome=str(row.get("outcome") or ""),
            outcome_index=_i(row, "outcomeIndex"),
            opposite_outcome=str(row.get("oppositeOutcome") or ""),
            opposite_asset=str(row.get("oppositeAsset") or ""),
            end_date=str(row.get("endDate") or ""),
            raw=row,
        )
    except (KeyError, TypeError, ValueError):
        return None


class PolymarketPositionsApi:
    def __init__(self, http_client: httpx.Client | None = None):
        self._http = http_client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._http.close()

    def current_positions(
        self,
        wallet: str,
        *,
        market: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "TOKENS",
        sort_direction: str = "DESC",
    ) -> list[CurrentPosition]:
        params: dict[str, Any] = {
            "user": wallet,
            "limit": limit,
            "offset": offset,
            "sortBy": sort_by,
            "sortDirection": sort_direction,
        }
        if market:
            params["market"] = market
        response = self._http.get(f"{DATA_API}/positions", params=params)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return []
        parsed = [parse_current_position(row) for row in rows]
        return [row for row in parsed if row is not None]

    def closed_positions(
        self,
        wallet: str,
        *,
        market: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "TIMESTAMP",
        sort_direction: str = "DESC",
    ) -> list[ClosedPosition]:
        params: dict[str, Any] = {
            "user": wallet,
            "limit": limit,
            "offset": offset,
            "sortBy": sort_by,
            "sortDirection": sort_direction,
        }
        if market:
            params["market"] = market
        response = self._http.get(f"{DATA_API}/closed-positions", params=params)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return []
        parsed = [parse_closed_position(row) for row in rows]
        return [row for row in parsed if row is not None]
