"""Demo replay (SPEC.md `DEMO_MODE=replay`): re-emit a recorded run into a fresh run.

    fixture = export_run(run_id)                 # a finished run + every emission, from SQLite
    result = await replay_run(rec, fixture)      # inside a traced run, like a live pipeline

A `RunFixture` is the run row (kind, request, result) plus its trace exactly as stored: every
emission in seq order, `started` and final states alike. Replaying emits them through the
recorder, so the new run is persisted and streamed like a live one, waiting between emissions
as long as the recording did, capped at `max_gap_s`.

Ids are remapped on the way out: the recorded run id becomes the new run's id, every event id a
fresh uuid (so two replays never share ids), and `ids` maps any other recorded id (the match
run a closer run read) to its live counterpart. The mapping is applied to every uuid anywhere in
the events and the result, prompts included, so "Why?" (`trace_event_id`) and tool arguments
keep pointing at the right things.
"""

import asyncio
import datetime as dt
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from app.schemas import RunKind, TraceEvent
from app.trace import store
from app.trace.recorder import TraceRecorder

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
Sleep = Callable[[float], Awaitable[None]]


class RunFixture(BaseModel):
    """One recorded run, replayable offline."""

    run_id: str  # the recorded run's id
    kind: RunKind
    request: dict[str, Any]
    result: dict[str, Any] | None
    recorded_at: dt.datetime
    events: list[TraceEvent]  # every emission, in seq order


class RunNotRecordable(RuntimeError):
    """The run is missing or didn't finish cleanly, so it can't become a fixture."""


def export_run(run_id: str) -> RunFixture:
    """A finished run (status `done`) and every stored emission, as a fixture."""
    run = store.get_run(run_id)
    if run is None:
        raise RunNotRecordable(f"no run {run_id}")
    if run.status != "done":
        raise RunNotRecordable(f"run {run_id} is {run.status}, not done")
    return RunFixture(
        run_id=run.id,
        kind=cast(RunKind, run.kind),
        request=run.request,
        result=run.result,
        recorded_at=run.created_at,
        events=store.load_events(run_id),
    )


def write_fixture(path: Path, fixture: RunFixture) -> Path:
    """Save `fixture` as JSON at `path` (creating its directory); returns `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fixture.model_dump_json(indent=1) + "\n")
    return path


def load_fixtures(directory: Path) -> list[RunFixture]:
    """Every run fixture in `directory` (`*.json`), by file name; [] if it doesn't exist."""
    return [
        RunFixture.model_validate_json(path.read_text())
        for path in sorted(directory.glob("*.json"))
    ]


class NoRecordedRun(LookupError):
    """Replay mode has no fixture for this request."""


RECORD_HINT = "record one with `make record-demo` (scripts/record_demo.py)"


def find_fixture(directory: Path, kind: RunKind, nct_id: str | None = None) -> RunFixture:
    """The recorded `kind` run to replay; for a closer run, the one on `nct_id`.

    HACK(demo): a match replays the recorded demo run whatever the request says (record_demo
    writes one `match.json`), so a reworded note on stage still gets the recording.
    """
    fixtures = [f for f in load_fixtures(directory) if f.kind == kind]
    if nct_id is not None:
        nct = nct_id.strip().upper()
        fixtures = [f for f in fixtures if str(f.request.get("nct_id", "")).upper() == nct]
    if not fixtures:
        what = f"{kind} run" + (f" on {nct_id}" if nct_id else "")
        raise NoRecordedRun(f"DEMO_MODE=replay: no recorded {what} in {directory}; {RECORD_HINT}")
    return fixtures[0]


def _emitted_at(event: TraceEvent) -> dt.datetime:
    """When the recorder emitted this: on start for `started`, on finish otherwise."""
    if event.status == "started" or event.ended_at is None:
        return event.started_at
    return event.ended_at


def _remap(value: Any, ids: dict[str, str]) -> Any:
    """`value` (JSON) with every mapped uuid replaced, inside strings and keys alike."""
    if isinstance(value, str):
        return UUID_RE.sub(lambda m: ids.get(m.group(), m.group()), value)
    if isinstance(value, dict):
        return {_remap(k, ids): _remap(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap(v, ids) for v in value]
    return value


async def replay_run(
    rec: TraceRecorder,
    fixture: RunFixture,
    *,
    max_gap_s: float,
    sleep: Sleep = asyncio.sleep,
    ids: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Emit the fixture's events into `rec`'s run with their original gaps (capped); return
    the recorded result, its ids remapped like the events'."""
    mapping = {e.id: str(uuid.uuid4()) for e in fixture.events}
    mapping.update(ids or {})
    mapping[fixture.run_id] = rec.run_id
    previous: dt.datetime | None = None
    for event in fixture.events:
        at = _emitted_at(event)
        if previous is not None:
            gap = (at - previous).total_seconds()
            await sleep(min(max(gap, 0.0), max_gap_s))
        previous = at
        rec.emit(TraceEvent.model_validate(_remap(event.model_dump(mode="json"), mapping)))
    result: dict[str, Any] | None = _remap(fixture.result, mapping)
    return result
