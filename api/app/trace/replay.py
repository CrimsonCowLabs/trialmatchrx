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
    # The demo patient id (scripts/record_demo.py DEMO_PATIENTS); a fixture saved without one
    # loads with its file stem instead.
    patient: str | None = None
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
    fixtures = []
    for path in sorted(directory.glob("*.json")):
        fixture = RunFixture.model_validate_json(path.read_text())
        fixture.patient = fixture.patient or path.stem
        fixtures.append(fixture)
    return fixtures


class NoRecordedRun(LookupError):
    """Replay mode has no fixture for this request."""


RECORD_HINT = "record it with `make record-demo` (scripts/record_demo.py)"


def normalize_note(note: str | None) -> str:
    """The note as replay compares it: whitespace collapsed, case folded."""
    return " ".join((note or "").split()).casefold()


def find_match_fixture(directory: Path, note: str | None) -> RunFixture:
    """The recorded match run whose note is `note` (whitespace/case-normalized).

    HACK(demo): replay only knows the demo patients' notes (web/lib/demo.ts); any other note,
    or a FHIR bundle, has no recording and fails clearly instead of replaying another patient.
    """
    fixtures = [f for f in load_fixtures(directory) if f.kind == "match"]
    if not fixtures:
        raise NoRecordedRun(f"replay mode: no recorded match run in {directory}; {RECORD_HINT}")
    wanted = normalize_note(note)
    for fixture in fixtures:
        if wanted and normalize_note(fixture.request.get("note")) == wanted:
            return fixture
    recorded = ", ".join(str(f.patient) for f in fixtures)
    raise NoRecordedRun(
        f"replay mode: no recording for this note (recorded patients: {recorded}); "
        f"use a demo patient's note unchanged, or {RECORD_HINT}"
    )


def find_closer_fixture(directory: Path, match_note: str | None, nct_id: str) -> RunFixture:
    """The closer run on `nct_id` recorded on the match run of the patient whose note is
    `match_note` (the closer fixture's `request.run_id` is that recorded match run's id)."""
    match = find_match_fixture(directory, match_note)
    nct = nct_id.strip().upper()
    for fixture in load_fixtures(directory):
        if (
            fixture.kind == "closer"
            and fixture.request.get("run_id") == match.run_id
            and str(fixture.request.get("nct_id", "")).upper() == nct
        ):
            return fixture
    raise NoRecordedRun(
        f"replay mode: no recorded closer run on {nct_id} for patient {match.patient} "
        f"in {directory}; {RECORD_HINT}"
    )


def recorded_patients(directory: Path) -> tuple[list[str], bool]:
    """The patients with both a match and a closer recording, and whether every recorded
    match has its closer."""
    fixtures = load_fixtures(directory)
    closer_on = {str(f.request.get("run_id")) for f in fixtures if f.kind == "closer"}
    matches = [f for f in fixtures if f.kind == "match"]
    complete = [str(f.patient) for f in matches if f.run_id in closer_on]
    return complete, len(complete) == len(matches)


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
