"""In-process async event bus for normalized market data."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from hermes_polymarket.data_sources.base import DataEvent


class EventBus:
    def __init__(self, maxsize: int = 100_000):
        self._queue: asyncio.Queue[DataEvent] = asyncio.Queue(maxsize=maxsize)
        self.dropped_events = 0

    async def publish(self, event: DataEvent) -> bool:
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.dropped_events += 1
            return False

    async def next_event(self) -> DataEvent:
        return await self._queue.get()

    async def stream(self) -> AsyncIterator[DataEvent]:
        while True:
            yield await self.next_event()

    def qsize(self) -> int:
        return self._queue.qsize()

