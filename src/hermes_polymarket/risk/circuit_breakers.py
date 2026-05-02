"""Circuit breaker helpers."""

from __future__ import annotations


def live_gate(allow_live_trading: bool, live_flag: bool) -> tuple[bool, str]:
    if not allow_live_trading:
        return False, "ALLOW_LIVE_TRADING is not true"
    if not live_flag:
        return False, "explicit --live flag is required"
    return True, "live gate passed"

