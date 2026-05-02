"""CLOB V2 public and private client helpers.

The pip package is `py-clob-client-v2`, but the Python import path exposed by
the official docs remains `py_clob_client`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from hermes_polymarket.config import Settings
from hermes_polymarket.polymarket.orderbook import parse_orderbook
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, TokenInfo


@dataclass
class PrivateClientState:
    available: bool
    reason: str = ""
    client: Any | None = None


class ClobV2Client:
    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self.settings = settings
        self._http = http_client or httpx.Client(timeout=15.0)
        self._sdk_public: Any | None = None
        self._sdk_private: Any | None = None

    def close(self) -> None:
        self._http.close()

    def _sdk_client(self, *, private: bool = False) -> Any | None:
        try:
            from py_clob_client.client import ClobClient
        except Exception:
            return None

        if private:
            if self._sdk_private is None:
                if not self.settings.private_key:
                    return None
                builder_config = {"builderCode": self.settings.builder_code} if self.settings.builder_code else None
                self._sdk_private = ClobClient(
                    host=self.settings.polymarket_host,
                    chain=self.settings.polygon_chain_id,
                    key=self.settings.private_key,
                    funder=self.settings.funder or None,
                    builder_config=builder_config,
                )
            return self._sdk_private

        if self._sdk_public is None:
            self._sdk_public = ClobClient(
                host=self.settings.polymarket_host,
                chain=self.settings.polygon_chain_id,
            )
        return self._sdk_public

    def health(self) -> Any:
        sdk = self._sdk_client()
        if sdk is not None and hasattr(sdk, "get_ok"):
            return sdk.get_ok()
        return self._get("/").text or {"ok": True}

    def get_markets(self, next_cursor: str | None = None) -> dict[str, Any]:
        sdk = self._sdk_client()
        if sdk is not None and hasattr(sdk, "get_markets"):
            if next_cursor:
                return sdk.get_markets(next_cursor=next_cursor)
            return sdk.get_markets()
        params = {"next_cursor": next_cursor} if next_cursor else None
        data = self._get("/markets", params=params).json()
        return data if isinstance(data, dict) else {"data": data}

    def get_market(self, condition_id: str) -> dict[str, Any]:
        sdk = self._sdk_client()
        for name in ("get_market", "get_market_info"):
            if sdk is not None and hasattr(sdk, name):
                try:
                    return getattr(sdk, name)(condition_id)
                except TypeError:
                    pass
        return self._get(f"/markets/{condition_id}").json()

    def get_clob_market_info(self, condition_id: str) -> MarketMetadata:
        sdk = self._sdk_client()
        raw: dict[str, Any]
        for name in ("get_clob_market_info", "getClobMarketInfo"):
            if sdk is not None and hasattr(sdk, name):
                raw = getattr(sdk, name)(condition_id)
                return parse_market_metadata(condition_id, raw)
        raw = self._get(f"/markets/{condition_id}").json()
        return parse_market_metadata(condition_id, raw)

    def get_orderbook(self, token_id: str) -> OrderBook:
        sdk = self._sdk_client()
        raw: dict[str, Any]
        if sdk is not None and hasattr(sdk, "get_order_book"):
            book = sdk.get_order_book(token_id)
            raw = book if isinstance(book, dict) else getattr(book, "__dict__", {})
        else:
            raw = self._get("/book", params={"token_id": token_id}).json()
        return parse_orderbook(token_id, raw)

    def get_midpoint(self, token_id: str) -> float | None:
        data = self._get("/midpoint", params={"token_id": token_id}).json()
        value = data.get("mid")
        return float(value) if value is not None else None

    def get_spread(self, token_id: str) -> float | None:
        data = self._get("/spread", params={"token_id": token_id}).json()
        value = data.get("spread")
        return float(value) if value is not None else None

    def private_client_state(self) -> PrivateClientState:
        if not self.settings.private_key:
            return PrivateClientState(False, "missing_private_key")
        client = self._sdk_client(private=True)
        if client is None:
            return PrivateClientState(False, "py_clob_client_sdk_unavailable")
        return PrivateClientState(True, client=client)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.settings.polymarket_host.rstrip('/')}{path}"
        response = self._http.get(url, params=params)
        response.raise_for_status()
        return response


def _token(raw: dict[str, Any]) -> TokenInfo:
    token_id = raw.get("t") or raw.get("token_id") or raw.get("tokenId") or raw.get("id")
    outcome = raw.get("o") or raw.get("outcome") or raw.get("name")
    return TokenInfo(token_id=str(token_id), outcome=str(outcome))


def parse_market_metadata(condition_id: str, raw: dict[str, Any]) -> MarketMetadata:
    tokens_raw = raw.get("t") or raw.get("tokens") or []
    tokens = tuple(_token(t) for t in tokens_raw if isinstance(t, dict))
    fee_raw = raw.get("fd") or raw.get("fee_details") or {}
    return MarketMetadata(
        condition_id=condition_id or str(raw.get("condition_id") or raw.get("conditionId") or ""),
        min_tick_size=float(raw.get("mts") or raw.get("minimum_tick_size") or raw.get("orderPriceMinTickSize") or 0.01),
        min_order_size=float(raw.get("mos") or raw.get("minimum_order_size") or raw.get("minimumOrderSize") or 1.0),
        tokens=tokens,
        fee_details=FeeDetails(
            rate=float(fee_raw.get("r") or fee_raw.get("rate") or 0.0),
            exponent=float(fee_raw.get("e") or fee_raw.get("exponent") or 1.0),
            taker_only=bool(fee_raw.get("to", fee_raw.get("taker_only", True))),
        ),
        neg_risk=bool(raw.get("neg_risk") or raw.get("negRisk") or False),
        raw=raw,
    )

