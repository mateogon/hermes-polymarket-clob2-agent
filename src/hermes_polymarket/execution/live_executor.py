"""Live executor stub with explicit gates."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.config import Settings
from hermes_polymarket.risk.circuit_breakers import live_gate


@dataclass(frozen=True)
class LiveGateResult:
    allowed: bool
    reason: str


class LiveExecutor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def check_gate(self, *, live_flag: bool) -> LiveGateResult:
        allowed, reason = live_gate(self.settings.allow_live_trading, live_flag)
        return LiveGateResult(allowed, reason)

    def place_order(self, *, live_flag: bool) -> None:
        gate = self.check_gate(live_flag=live_flag)
        if not gate.allowed:
            raise PermissionError(gate.reason)
        raise NotImplementedError("Live order posting is intentionally disabled until pre-live review passes")

