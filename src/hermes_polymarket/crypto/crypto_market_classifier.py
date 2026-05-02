"""Heuristics for identifying short-duration crypto markets."""

from __future__ import annotations

import re


SYMBOL_PATTERNS = {
    "btcusdt": [r"\bbitcoin\b", r"\bbtc\b"],
    "ethusdt": [r"\bethereum\b", r"\bether\b", r"\beth\b"],
    "solusdt": [r"\bsolana\b", r"\bsol\b"],
    "xrpusdt": [r"\bxrp\b", r"\bripple\b"],
}

TIME_PATTERNS = (
    "5m",
    "5-min",
    "5 min",
    "5 minute",
    "five minute",
    "15m",
    "15-min",
    "15 min",
    "15 minute",
    "fifteen minute",
    "hour",
    "1h",
    "up or down",
    "up-or-down",
    "rise or fall",
    "rise-or-fall",
    "higher or lower",
    "higher-or-lower",
    "above or below",
    "above-or-below",
)


def infer_symbol_from_text(text: str) -> str | None:
    lowered = text.lower()
    for symbol, patterns in SYMBOL_PATTERNS.items():
        if any(re.search(pattern, lowered) for pattern in patterns):
            return symbol
    return None


def crypto_market_reject_reason(title: str, slug: str) -> str | None:
    text = f"{title} {slug}".lower()
    if infer_symbol_from_text(text) is None:
        return "no_crypto_symbol"
    if not any(marker in text for marker in TIME_PATTERNS):
        return "no_time_bucket"
    return None


def is_short_duration_crypto_market(title: str, slug: str) -> bool:
    return crypto_market_reject_reason(title, slug) is None
