"""Diagnostics collected during crypto latency recordings."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecorderDiagnostics:
    events_seen_by_source: Counter[str] = field(default_factory=Counter)
    readings_by_source: Counter[str] = field(default_factory=Counter)
    consensus_ticks_by_symbol: Counter[str] = field(default_factory=Counter)
    latency_events_by_symbol: Counter[str] = field(default_factory=Counter)
    rejected_consensus_reasons: Counter[str] = field(default_factory=Counter)
    reconnect_errors_by_source: Counter[str] = field(default_factory=Counter)
    threshold_hits_by_symbol: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))

    def seen_event(self, source: str) -> None:
        self.events_seen_by_source[source] += 1

    def seen_reading(self, source: str) -> None:
        self.readings_by_source[source] += 1

    def seen_consensus(self, symbol: str) -> None:
        self.consensus_ticks_by_symbol[symbol] += 1

    def seen_latency_event(self, symbol: str) -> None:
        self.latency_events_by_symbol[symbol] += 1

    def rejected_consensus(self, reason: str) -> None:
        self.rejected_consensus_reasons[reason] += 1

    def reconnect_error(self, source: str) -> None:
        self.reconnect_errors_by_source[source] += 1

    def threshold_hit(self, symbol: str, threshold_pct: float) -> None:
        self.threshold_hits_by_symbol[symbol][str(threshold_pct)] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "events_seen_by_source": dict(self.events_seen_by_source),
            "readings_by_source": dict(self.readings_by_source),
            "consensus_ticks_by_symbol": dict(self.consensus_ticks_by_symbol),
            "latency_events_by_symbol": dict(self.latency_events_by_symbol),
            "rejected_consensus_reasons": dict(self.rejected_consensus_reasons),
            "reconnect_errors_by_source": dict(self.reconnect_errors_by_source),
            "threshold_hits_by_symbol": {
                symbol: dict(counter)
                for symbol, counter in self.threshold_hits_by_symbol.items()
            },
        }
