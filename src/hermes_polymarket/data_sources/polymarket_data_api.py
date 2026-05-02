"""Public Polymarket Data API client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DATA_API = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class WalletTrade:
    wallet: str
    side: str
    condition_id: str
    asset_id: str
    outcome: str
    price: float
    size: float
    timestamp: int
    slug: str
    title: str
    tx_hash: str
    raw: dict[str, Any]

    @property
    def notional_usd(self) -> float:
        return self.price * self.size


class PolymarketDataApi:
    def __init__(self, http_client: httpx.Client | None = None):
        self._http = http_client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._http.close()

    def get_trades_for_wallet(
        self,
        wallet: str,
        *,
        limit: int = 100,
        offset: int = 0,
        side: str | None = None,
        min_cash: float | None = None,
    ) -> list[WalletTrade]:
        params: dict[str, Any] = {
            "user": wallet,
            "limit": limit,
            "offset": offset,
            "takerOnly": "true",
        }
        if side:
            params["side"] = side.upper()
        if min_cash is not None:
            params["filterType"] = "CASH"
            params["filterAmount"] = min_cash

        response = self._http.get(f"{DATA_API}/trades", params=params)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return []
        parsed = [parse_wallet_trade(row) for row in rows]
        return [trade for trade in parsed if trade is not None]


def parse_wallet_trade(row: Any) -> WalletTrade | None:
    if not isinstance(row, dict):
        return None
    try:
        return WalletTrade(
            wallet=str(row["proxyWallet"]),
            side=str(row["side"]).upper(),
            condition_id=str(row["conditionId"]),
            asset_id=str(row["asset"]),
            outcome=str(row["outcome"]),
            price=float(row["price"]),
            size=float(row["size"]),
            timestamp=int(row["timestamp"]),
            slug=str(row.get("slug") or ""),
            title=str(row.get("title") or row.get("name") or ""),
            tx_hash=str(row.get("transactionHash") or ""),
            raw=row,
        )
    except (KeyError, TypeError, ValueError):
        return None

