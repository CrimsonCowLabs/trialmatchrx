"""Run status, trace export and the live SSE stream."""

from typing import Any, cast

from fastapi import APIRouter, Header, HTTPException
from sse_starlette import EventSourceResponse

from app.db import RunRow
from app.schemas import PatientFacts, RunKind, RunStatus, RunSummary, RunTotals, TraceEvent
from app.trace import store
from app.trace.bus import bus
from app.trace.stream import run_event_stream

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _require_run(run_id: str) -> RunRow:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run


def compute_totals(run: RunRow, events: list[TraceEvent]) -> RunTotals:
    llm = [e for e in events if e.kind == "llm"]
    wall = (run.ended_at - run.created_at).total_seconds() if run.ended_at else None
    return RunTotals(
        llm_calls=len(llm),
        tokens_in=sum(e.tokens_in or 0 for e in llm),
        tokens_out=sum(e.tokens_out or 0 for e in llm),
        cost_usd=sum(e.cost_usd or 0.0 for e in llm),
        cache_hits=sum(1 for e in events if e.cache_hit),
        wall_time_s=wall,
    )


@router.get("/{run_id}/events", response_class=EventSourceResponse)
async def stream_run_events(
    run_id: str, last_event_id: int | None = Header(default=None)
) -> EventSourceResponse:
    """SSE: `trace` events (data = TraceEvent, id = seq), stored first then live, then one
    `done` event (data = RunDone). Honours `Last-Event-ID` on reconnect."""
    _require_run(run_id)
    return EventSourceResponse(run_event_stream(run_id, bus, after_seq=last_event_id or 0))


@router.get("/{run_id}", response_model=RunSummary)
async def get_run(run_id: str) -> RunSummary:
    run = _require_run(run_id)
    result: dict[str, Any] = run.result or {}
    patient = result.get("patient")
    return RunSummary(
        run_id=run.id,
        kind=cast(RunKind, run.kind),
        status=cast(RunStatus, run.status),
        patient=PatientFacts.model_validate(patient) if patient else None,
        matches=result.get("matches", []),
        totals=compute_totals(run, store.latest_events(run_id)),
    )


@router.get("/{run_id}/trace", response_model=list[TraceEvent])
async def get_run_trace(run_id: str) -> list[TraceEvent]:
    """Every event of the run in its final state, ordered by first appearance."""
    _require_run(run_id)
    return store.latest_events(run_id)
