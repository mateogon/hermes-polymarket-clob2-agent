"""Shared signal types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Signal:
    market_id: str
    outcome: str
    model_probability: float
    confidence: float
    reason: str
    sources: tuple[str, ...] = field(default_factory=tuple)

