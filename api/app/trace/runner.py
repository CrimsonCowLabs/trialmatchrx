"""How a router starts a traced run.

Background (match, closer): returns the run id at once, work continues in a task.

    run_id = start_traced_run("match", req.model_dump(mode="json"), work)

    async def work(rec: TraceRecorder) -> dict | None:
        async with rec.step("parse_patient", "step", {...}) as s:
            ...
        return {"patient": ..., "matches": [...]}   # stored as runs.result

Inline (compile): the request waits for the work, but it is still a run with a trace.

    async with traced_run("compile", {"nct": nct}) as run:
        criteria = await compile(run.recorder, ...)
        run.result = {"criteria": [...]}

Either way the run row is marked done/failed at the end and SSE subscribers get `done`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.schemas import RunKind
from app.trace import store
from app.trace.bus import EventBus
from app.trace.bus import bus as default_bus
from app.trace.recorder import TraceRecorder, describe_error

log = logging.getLogger(__name__)

RunWork = Callable[[TraceRecorder], Awaitable[dict[str, Any] | None]]

# Strong references so background runs aren't garbage-collected mid-flight.
_background: set[asyncio.Task[None]] = set()


@dataclass
class TracedRun:
    run_id: str
    recorder: TraceRecorder
    result: dict[str, Any] | None = None


@asynccontextmanager
async def traced_run(
    kind: RunKind,
    request: dict[str, Any],
    *,
    run_id: str | None = None,
    bus: EventBus = default_bus,
) -> AsyncIterator[TracedRun]:
    """Open a run (creating its row unless `run_id` names an existing one) and close it."""
    if run_id is None:
        run_id = store.create_run(kind, request)
    run = TracedRun(run_id, TraceRecorder(run_id, bus))
    try:
        yield run
    except BaseException as exc:
        message = describe_error(exc)
        run.recorder.event(kind, "error", status="failed", output={"error": message})
        store.finish_run(run_id, "failed", result=run.result, error=message)
        raise
    else:
        store.finish_run(run_id, "done", result=run.result)
    finally:
        bus.close(run_id)


def start_traced_run(
    kind: RunKind, request: dict[str, Any], work: RunWork, *, bus: EventBus = default_bus
) -> str:
    """Create the run row now, run `work` in a background task, return the run id."""
    run_id = store.create_run(kind, request)

    async def drive() -> None:
        try:
            async with traced_run(kind, request, run_id=run_id, bus=bus) as run:
                run.result = await work(run.recorder)
        except Exception:
            log.exception("run %s (%s) failed", run_id, kind)

    task = asyncio.create_task(drive(), name=f"run:{kind}:{run_id}")
    _background.add(task)
    task.add_done_callback(_background.discard)
    return run_id
