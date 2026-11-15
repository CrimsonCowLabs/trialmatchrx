"""Run totals are computed from the run's trace events, whoever emitted them."""

from app.routers.runs import compute_totals
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder


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
