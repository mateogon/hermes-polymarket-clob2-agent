"""Helpers for seeding crypto latency watchlist windows.

These helpers use public Gamma and public crypto price endpoints only. They do
not trade and do not require authentication.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from hermes_polymarket.crypto.market_resolver import infer_crypto_symbol, market_window_from_gamma_market
from hermes_polymarket.data_sources.base import now_ms
from hermes_polymarket.signals.source_consensus import PriceReading, consensus_price


GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass(frozen=True)
class WatchlistSeed:
    condition_id: str
    slug: str
    question: str
    symbol: str
    yes_token_id: str
    no_token_id: str
    up_token_id: str
    down_token_id: str
    reference_price: float
    window_start_ts: int
    window_end_ts: int
    consensus_sources: tuple[str, ...]
    max_deviation_pct: float

    def to_watchlist_row(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "slug": self.slug,
            "question": self.question,
            "symbol": self.symbol,
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "direction_map": {"up": self.up_token_id, "down": self.down_token_id},
            "active": True,
            "discovered_at_ms": self.window_start_ts * 1000,
            "end_ts_ms": self.window_end_ts * 1000,
            "raw": {
                "manual_current_window": True,
                "reference_price": self.reference_price,
                "window_start_ts": self.window_start_ts,
                "window_end_ts": self.window_end_ts,
                "consensus_sources": list(self.consensus_sources),
                "max_deviation_pct": self.max_deviation_pct,
            },
        }


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _token_ids(market: dict[str, Any]) -> tuple[str, str] | None:
    tokens = _coerce_list(market.get("tokens"))
    if len(tokens) >= 2:
        first, second = tokens[0], tokens[1]
        yes_token = first.get("token_id") or first.get("id") if isinstance(first, dict) else first
        no_token = second.get("token_id") or second.get("id") if isinstance(second, dict) else second
        if yes_token and no_token:
            return str(yes_token), str(no_token)
    clob_tokens = _coerce_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    if len(clob_tokens) >= 2:
        return str(clob_tokens[0]), str(clob_tokens[1])
    return None


def fetch_gamma_market_by_slug(slug: str, *, http_client: httpx.Client | None = None) -> dict[str, Any]:
    close = http_client is None
    client = http_client or httpx.Client(timeout=15.0)
    try:
        response = client.get(f"{GAMMA_API}/markets", params={"slug": slug})
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Gamma returned no market for slug: {slug}")
        market = rows[0]
        if not isinstance(market, dict):
            raise ValueError(f"Gamma market payload is not an object for slug: {slug}")
        return market
    finally:
        if close:
            client.close()


def _binance_price(client: httpx.Client, symbol: str) -> PriceReading | None:
    response = client.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol.upper()})
    response.raise_for_status()
    payload = response.json()
    price = payload.get("price") if isinstance(payload, dict) else None
    return PriceReading("binance_rest", symbol, float(price), now_ms()) if price is not None else None


def _coinbase_price(client: httpx.Client, symbol: str) -> PriceReading | None:
    product = symbol.replace("usdt", "-USD").upper()
    response = client.get(f"https://api.exchange.coinbase.com/products/{product}/ticker")
    response.raise_for_status()
    payload = response.json()
    price = payload.get("price") if isinstance(payload, dict) else None
    return PriceReading("coinbase_rest", symbol, float(price), now_ms()) if price is not None else None


def _kraken_pair(symbol: str) -> str:
    base = symbol.removesuffix("usdt").upper()
    if base == "BTC":
        base = "XBT"
    return f"{base}USD"


def _kraken_price(client: httpx.Client, symbol: str) -> PriceReading | None:
    response = client.get("https://api.kraken.com/0/public/Ticker", params={"pair": _kraken_pair(symbol)})
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not result:
        return None
    first = next(iter(result.values()))
    close = first.get("c") if isinstance(first, dict) else None
    if not isinstance(close, list) or not close:
        return None
    return PriceReading("kraken_rest", symbol, float(close[0]), now_ms())


def current_reference_consensus(
    symbol: str,
    *,
    http_client: httpx.Client | None = None,
    min_sources: int = 2,
    max_deviation_pct: float = 0.25,
) -> tuple[float, tuple[str, ...], float]:
    close = http_client is None
    client = http_client or httpx.Client(timeout=15.0)
    readings: list[PriceReading] = []
    try:
        for fetcher in (_binance_price, _coinbase_price, _kraken_price):
            try:
                reading = fetcher(client, symbol)
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                reading = None
            if reading is not None:
                readings.append(reading)

        current = consensus_price(
            readings,
            now_ms=now_ms(),
            max_age_ms=10_000,
            max_deviation_pct_allowed=max_deviation_pct,
            min_sources=min_sources,
        )
        if current is None:
            sources = [r.source for r in readings]
            raise ValueError(f"Could not build current reference consensus for {symbol}; sources={sources}")
        return current.price, current.sources, current.max_deviation_pct
    finally:
        if close:
            client.close()


def seed_current_window_from_slug(
    *,
    slug: str,
    symbol: str | None = None,
    yes_direction: str,
    duration_seconds: int,
    http_client: httpx.Client | None = None,
    now_ts: int | None = None,
    min_sources: int = 2,
    max_deviation_pct: float = 0.25,
) -> WatchlistSeed:
    if yes_direction not in {"up", "down"}:
        raise ValueError("yes_direction must be up or down")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")

    close = http_client is None
    client = http_client or httpx.Client(timeout=15.0)
    try:
        market = fetch_gamma_market_by_slug(slug, http_client=client)
        if bool(market.get("closed")) or not bool(market.get("active", True)):
            raise ValueError(f"Gamma market is not active/open for slug: {slug}")
        resolved = market_window_from_gamma_market(market)
        tokens = _token_ids(market)
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
        question = str(market.get("question") or market.get("title") or slug)
        inferred_symbol = symbol or (resolved or {}).get("symbol") or infer_crypto_symbol(f"{slug} {question}")
        if not inferred_symbol:
            raise ValueError(f"Could not infer symbol for slug: {slug}; pass --symbol")
        if tokens is None:
            raise ValueError(f"Could not find CLOB token ids for slug: {slug}")
        if not condition_id:
            raise ValueError(f"Could not find conditionId for slug: {slug}")

        yes_token_id, no_token_id = tokens
        if yes_direction == "up":
            up_token_id, down_token_id = yes_token_id, no_token_id
        else:
            up_token_id, down_token_id = no_token_id, yes_token_id

        reference_price, sources, max_dev = current_reference_consensus(
            str(inferred_symbol).lower(),
            http_client=client,
            min_sources=min_sources,
            max_deviation_pct=max_deviation_pct,
        )
        start_ts = int(now_ts if now_ts is not None else now_ms() // 1000)
        return WatchlistSeed(
            condition_id=condition_id,
            slug=str(market.get("slug") or slug),
            question=question,
            symbol=str(inferred_symbol).lower(),
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
            reference_price=reference_price,
            window_start_ts=start_ts,
            window_end_ts=start_ts + int(duration_seconds),
            consensus_sources=sources,
            max_deviation_pct=max_dev,
        )
    finally:
        if close:
            client.close()
