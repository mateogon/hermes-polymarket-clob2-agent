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

    def search_markets(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        response = self._http.get(f"{GAMMA_BASE}/markets", params={"_q": query, "limit": limit, "active": "true", "closed": "false"})
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def active_markets(self, limit: int = 50) -> list[dict[str, Any]]:
        response = self._http.get(f"{GAMMA_BASE}/markets", params={"limit": limit, "active": "true", "closed": "false"})
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
