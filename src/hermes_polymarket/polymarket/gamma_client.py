"""Small Gamma API client used for market discovery only."""

from __future__ import annotations

from typing import Any

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"


class GammaClient:
    def __init__(self, http_client: httpx.Client | None = None):
        self._http = http_client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        self._http.close()

    def list_markets(self, **params: Any) -> list[dict[str, Any]]:
        response = self._http.get(f"{GAMMA_BASE}/markets", params=params)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def search_markets(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_markets(_q=query, limit=limit, active="true", closed="false")

    def active_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_markets(limit=limit, active="true", closed="false")

    def markets_by_slug(self, slug: str) -> list[dict[str, Any]]:
        return self.list_markets(slug=slug, limit=10)

    def markets_by_condition_id(self, condition_id: str) -> list[dict[str, Any]]:
        return self.list_markets(condition_ids=condition_id, limit=10)

    def markets_by_token_id(self, token_id: str) -> list[dict[str, Any]]:
        return self.list_markets(clob_token_ids=token_id, limit=10)
