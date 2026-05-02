"""Public CLOB smoke check.

This script intentionally requires no private key and never posts orders.
"""

from __future__ import annotations

import json

import httpx

from hermes_polymarket.config import Settings, load_settings
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client


def _market_list(markets: dict) -> list[dict]:
    data = markets.get("data") or markets.get("markets") or []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _has_orderbook(market: dict) -> bool:
    return bool(market.get("accepting_orders")) and not bool(market.get("closed"))


def _gamma_token_ids(market: dict) -> list[str]:
    raw = market.get("clobTokenIds") or market.get("clob_token_ids") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return [str(token_id) for token_id in raw if token_id]


def run_smoke(settings: Settings | None = None) -> bool:
    settings = settings or load_settings()
    client = ClobV2Client(settings)
    gamma = GammaClient()
    try:
        health = client.health()
        print(f"health={health!r}")

        cursor: str | None = None
        scanned = 0
        for _ in range(8):
            markets = client.get_markets(cursor)
            candidates = _market_list(markets)
            scanned += len(candidates)
            for market in [m for m in candidates if _has_orderbook(m)][:50]:
                condition_id = str(market.get("condition_id") or market.get("conditionId") or "")
                if not condition_id:
                    continue
                info = client.get_clob_market_info(condition_id)
                for token in info.tokens:
                    try:
                        book = client.get_orderbook(token.token_id)
                    except httpx.HTTPStatusError:
                        continue
                    print(f"condition_id={condition_id}")
                    print(f"tokens={len(info.tokens)} min_tick={info.min_tick_size} min_order={info.min_order_size}")
                    print(f"book token={token.token_id} bids={len(book.bids)} asks={len(book.asks)}")
                    return True
            cursor = markets.get("next_cursor")
            if not cursor:
                break
        print(f"markets_scanned={scanned}")

        for market in gamma.active_markets(limit=50):
            for token_id in _gamma_token_ids(market):
                try:
                    book = client.get_orderbook(token_id)
                except httpx.HTTPStatusError:
                    continue
                print(f"gamma_market={market.get('question') or market.get('slug')}")
                print(f"book token={token_id} bids={len(book.bids)} asks={len(book.asks)}")
                return True

        print("no_orderbook_found=true")
        return False
    finally:
        client.close()
        gamma.close()


if __name__ == "__main__":
    raise SystemExit(0 if run_smoke() else 1)
