"""Conservative crypto market discovery helpers.

This module only prepares public market-window candidates. It does not trade.
The first implementation intentionally favors transparent heuristics over broad
automation; local L2 replay can make this stricter later.
"""

from __future__ import annotations

import json
from typing import Any

from hermes_polymarket.crypto.crypto_market_classifier import infer_symbol_from_text, is_short_duration_crypto_market


SYMBOL_KEYWORDS = {
    "btcusdt": ("bitcoin", "btc"),
    "ethusdt": ("ethereum", "eth"),
    "solusdt": ("solana", "sol"),
    "xrpusdt": ("xrp", "ripple"),
}


def infer_crypto_symbol(text: str) -> str | None:
    return infer_symbol_from_text(text)


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
        first = tokens[0]
        second = tokens[1]
        yes_token = str(first.get("token_id") or first.get("id") if isinstance(first, dict) else first)
        no_token = str(second.get("token_id") or second.get("id") if isinstance(second, dict) else second)
        if yes_token and no_token:
            return yes_token, no_token
    clob_tokens = _coerce_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    if len(clob_tokens) >= 2:
        return str(clob_tokens[0]), str(clob_tokens[1])
    return None


def market_window_from_gamma_market(market: dict[str, Any]) -> dict[str, Any] | None:
    slug = str(market.get("slug") or "")
    question = str(market.get("question") or market.get("title") or "")
    if not is_short_duration_crypto_market(question, slug):
        return None
    symbol = infer_crypto_symbol(f"{slug} {question}")
    tokens = _token_ids(market)
    if symbol is None or tokens is None:
        return None
    yes_token, no_token = tokens
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
