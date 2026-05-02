"""Heuristics for identifying short-duration crypto markets."""

from __future__ import annotations

import re


SYMBOL_PATTERNS = {
    "btcusdt": [r"\bbitcoin\b", r"\bbtc\b"],
    "ethusdt": [r"\bethereum\b", r"\beth\b"],
    "solusdt": [r"\bsolana\b", r"\bsol\b"],
    "xrpusdt": [r"\bxrp\b", r"\bripple\b"],
}


def infer_symbol_from_text(text: str) -> str | None:
    lowered = text.lower()
    for symbol, patterns in SYMBOL_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            return symbol
    return None


def is_short_duration_crypto_market(title: str, slug: str) -> bool:
    text = f"{title} {slug}".lower()
    has_crypto = infer_symbol_from_text(text) is not None
    has_time_bucket = any(
        marker in text
        for marker in (
            "5m",
            "5-min",
            "5 minute",
            "15m",
            "15-min",
            "15 minute",
            "up or down",
            "up-or-down",
            "rise or fall",
            "rise-or-fall",
        )
    )
    return has_crypto and has_time_bucket
