"""Per-run in-process pub/sub feeding the SSE endpoint.

Each subscriber gets its own `asyncio.Queue`, so a refreshed page and a stale tab can both
listen to the same run. Publishing never blocks (queues are unbounded).
"""

import asyncio
import enum
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.schemas import TraceEvent


class BusSignal(enum.Enum):
    DONE = "done"


BusItem = TraceEvent | BusSignal
Subscription = asyncio.Queue[BusItem]


class EventBus:
    DONE = BusSignal.DONE

    def __init__(self) -> None:
        self._subs: defaultdict[str, set[Subscription]] = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[Subscription]:
        queue: Subscription = asyncio.Queue()
        self._subs[run_id].add(queue)
        try:
            yield queue
        finally:
            subs = self._subs.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subs[run_id]

    def publish(self, event: TraceEvent) -> None:
        for queue in self._subs.get(event.run_id, ()):
            queue.put_nowait(event)

    def close(self, run_id: str) -> None:
        """Tell current subscribers the run has finished."""
        for queue in self._subs.get(run_id, ()):
            queue.put_nowait(BusSignal.DONE)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subs.get(run_id, ()))


bus = EventBus()
"""The process-wide bus used by the app."""
