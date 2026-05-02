"""Runtime state for bounded crypto latency recordings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hermes_polymarket.signals.source_consensus import ConsensusPrice, PriceReading


@dataclass
class CryptoRuntimeState:
    readings_by_symbol: dict[str, dict[str, PriceReading]] = field(default_factory=dict)
    last_consensus_by_symbol: dict[str, ConsensusPrice] = field(default_factory=dict)
    last_event_ts_by_symbol: dict[str, int] = field(default_factory=dict)
    bbo_by_token_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    token_to_market: dict[str, dict[str, Any]] = field(default_factory=dict)

    def update_reading(self, reading: PriceReading) -> None:
        self.readings_by_symbol.setdefault(reading.symbol, {})[reading.source] = reading

    def readings(self, symbol: str) -> list[PriceReading]:
        return list(self.readings_by_symbol.get(symbol, {}).values())

    def update_bbo(self, token_id: str, payload: dict[str, Any]) -> None:
        self.bbo_by_token_id[token_id] = payload

    def market_for_token(self, token_id: str) -> dict[str, Any] | None:
        return self.token_to_market.get(token_id)
