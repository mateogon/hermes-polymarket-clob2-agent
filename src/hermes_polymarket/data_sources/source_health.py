"""Source health tracking for public data adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms


@dataclass(frozen=True)
class SourceHealth:
    source: str
    ok: bool
    checked_ts_ms: int
    message: str = ""
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> DataEvent:
        return DataEvent(
            source=self.source,
            event_type=EventType.SOURCE_HEALTH,
            event_ts_ms=self.checked_ts_ms,
            received_ts_ms=now_ms(),
            key=self.source,
            payload={
                "ok": self.ok,
                "message": self.message,
                "latency_ms": self.latency_ms,
                "details": self.details,
            },
        )


def healthy(source: str, *, latency_ms: int | None = None, **details: Any) -> SourceHealth:
    return SourceHealth(source=source, ok=True, checked_ts_ms=now_ms(), latency_ms=latency_ms, details=details)


def unhealthy(source: str, message: str, **details: Any) -> SourceHealth:
    return SourceHealth(source=source, ok=False, checked_ts_ms=now_ms(), message=message, details=details)
