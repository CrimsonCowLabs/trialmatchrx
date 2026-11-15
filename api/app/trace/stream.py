"""The SSE body for one run: stored events, then live ones, then `done`.

Subscribe to the bus *before* reading storage so nothing emitted in between is lost, then drop
live events whose seq was already sent from storage.
"""

from collections.abc import AsyncIterator
from typing import Any, cast

from app.schemas import RunDone, RunStatus, TraceEvent
from app.trace import store
from app.trace.bus import BusSignal, EventBus


def _trace_message(event: TraceEvent) -> dict[str, Any]:
    return {"event": "trace", "id": str(event.seq), "data": event.model_dump_json()}


def _done_message(run_id: str, status: RunStatus) -> dict[str, Any]:
    return {"event": "done", "data": RunDone(run_id=run_id, status=status).model_dump_json()}


async def run_event_stream(
    run_id: str, bus: EventBus, *, after_seq: int = 0
) -> AsyncIterator[dict[str, Any]]:
    async with bus.subscribe(run_id) as live:
        last_seq = after_seq
        for event in store.load_events(run_id, after_seq=after_seq):
            yield _trace_message(event)
            last_seq = event.seq

        run = store.get_run(run_id)
        if run is not None and run.status != "running":
            # It may have emitted more between the load above and finishing.
            for event in store.load_events(run_id, after_seq=last_seq):
                yield _trace_message(event)
            yield _done_message(run_id, cast(RunStatus, run.status))
            return

        while True:
            item = await live.get()
            if item is BusSignal.DONE:
                finished = store.get_run(run_id)
                status = finished.status if finished is not None else "done"
                yield _done_message(run_id, cast(RunStatus, status))
                return
            assert isinstance(item, TraceEvent)
            if item.seq > last_seq:
                yield _trace_message(item)
                last_seq = item.seq
