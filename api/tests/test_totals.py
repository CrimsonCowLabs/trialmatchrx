"""Run totals are computed from the run's trace events, whoever emitted them."""

import datetime as dt
import json
from pathlib import Path

import pytest

from app.db import RunRow
from app.routers.runs import compute_totals
from app.schemas import TraceEvent
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

SHARED_FIXTURE = Path(__file__).parent / "fixtures" / "trace" / "totals.json"


def test_guardrail_trips_count_failed_guardrail_events_only() -> None:
    rec = TraceRecorder(store.create_run("match", {}), EventBus())
    rec.event("verify:NCT1:inc-1", "guardrail", note="quotes verified")
    rec.event("verify:NCT1:inc-2", "guardrail", status="failed")
    rec.event("predicate:exc-3", "guardrail", status="failed")  # the compiler's, counts too
    rec.event("judge:NCT1:inc-4:malformed", "error", status="failed")  # an error, not a trip

    run = store.get_run(rec.run_id)
    assert run is not None
    totals = compute_totals(run, store.latest_events(rec.run_id))

    assert totals.guardrail_trips == 2


def test_totals_match_the_shared_fixture_the_web_live_strip_is_tested_against() -> None:
    # web/lib/trace.test.ts runs computeTotals over the same file, so the trace panel's live
    # totals and RunTotals are held to the same counting rules.
    doc = json.loads(SHARED_FIXTURE.read_text())
    events = [TraceEvent.model_validate(e) for e in doc["events"]]
    created = dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC)
    run = RunRow(id="r-fixture", kind="match", status="running", created_at=created)

    totals = compute_totals(run, events).model_dump()

    expected = dict(doc["expected"])
    assert totals["cost_usd"] == pytest.approx(expected.pop("cost_usd"))
    assert {k: totals[k] for k in expected} == expected
    assert totals["wall_time_s"] is None  # still running: wall time comes from the run row
