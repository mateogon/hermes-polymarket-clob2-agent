import asyncio

from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.data_sources.event_bus import EventBus
from hermes_polymarket.data_sources.source_health import healthy, unhealthy


def test_data_event_latency():
    event = DataEvent("src", EventType.BINANCE_TRADE, 1000, 1250, "btcusdt", {})
    assert event.latency_ms == 250


def test_event_bus_publish_and_read():
    bus = EventBus(maxsize=1)
    event = DataEvent("src", EventType.POLY_BOOK, None, 1, "token", {})
    assert asyncio.run(bus.publish(event)) is True
    assert asyncio.run(bus.next_event()) == event


def test_event_bus_reports_drops_when_full():
    bus = EventBus(maxsize=1)
    event = DataEvent("src", EventType.POLY_BOOK, None, 1, "token", {})
    assert asyncio.run(bus.publish(event)) is True
    assert asyncio.run(bus.publish(event)) is False
    assert bus.dropped_events == 1


def test_source_health_to_event():
    event = healthy("gamma", latency_ms=12).to_event()
    assert event.event_type == EventType.SOURCE_HEALTH
    assert event.payload["ok"] is True
    assert event.payload["latency_ms"] == 12

    bad = unhealthy("clob", "timeout").to_event()
    assert bad.payload["ok"] is False
    assert bad.payload["message"] == "timeout"
