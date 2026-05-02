"""In-memory source health projection."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.data_sources.base import DataEvent, EventType


@dataclass
class SourceStatus:
    source: str
    last_seen_ts_ms: int
    last_latency_ms: int | None = None
    messages_seen: int = 0
    errors_seen: int = 0
    dropped_events: int = 0
    status: str = "unknown"


class SourceState:
    def __init__(self):
        self.sources: dict[str, SourceStatus] = {}

    def apply(self, event: DataEvent, *, dropped_events: int = 0) -> SourceStatus:
        status = self.sources.get(event.source)
        if status is None:
            status = SourceStatus(event.source, event.received_ts_ms)
            self.sources[event.source] = status
        status.last_seen_ts_ms = event.received_ts_ms
        status.last_latency_ms = event.latency_ms
        status.messages_seen += 1
        status.dropped_events += dropped_events
        ok = event.payload.get("ok")
        if event.event_type == EventType.SOURCE_HEALTH and ok is False:
            status.errors_seen += 1
            status.status = "error"
        else:
            status.status = "ok"
        return status
