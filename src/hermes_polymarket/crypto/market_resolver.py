"""Conservative crypto market discovery helpers.

This module only prepares public market-window candidates. It does not trade.
The first implementation intentionally favors transparent heuristics over broad
automation; local L2 replay can make this stricter later.
"""

from __future__ import annotations

from typing import Any


SYMBOL_KEYWORDS = {
    "btcusdt": ("bitcoin", "btc"),
    "ethusdt": ("ethereum", "eth"),
    "solusdt": ("solana", "sol"),
    "xrpusdt": ("xrp", "ripple"),
}


def infer_crypto_symbol(text: str) -> str | None:
    lowered = text.lower()
    for symbol, keywords in SYMBOL_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return symbol
    return None


def market_window_from_gamma_market(market: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(market.get("slug") or "")
    question = str(market.get("question") or market.get("title") or "")
    symbol = infer_crypto_symbol(f"{slug} {question}")
    tokens = market.get("tokens") or market.get("clobTokenIds") or []
    if symbol is None or not isinstance(tokens, list) or len(tokens) < 2:
        return None
    yes_token = str(tokens[0].get("token_id") if isinstance(tokens[0], dict) else tokens[0])
    no_token = str(tokens[1].get("token_id") if isinstance(tokens[1], dict) else tokens[1])
    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    if not condition_id or not yes_token or not no_token:
        return None
    return {
        "condition_id": condition_id,
        "slug": slug,
        "question": question,
        "symbol": symbol,
        "yes_token_id": yes_token,
        "no_token_id": no_token,
        "window_start_ts": market.get("window_start_ts"),
        "window_end_ts": market.get("window_end_ts"),
        "reference_price": market.get("reference_price"),
        "active": bool(market.get("active", True)),
    }
