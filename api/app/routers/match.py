"""POST /api/match and POST /api/closer: start a background run, return its id."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.pipeline.compile_criteria import ModelFactory
from app.pipeline.match_run import run_match
from app.pipeline.parse_patient import anthropic_parse_model
from app.routers.trials import compile_model_factory
from app.schemas import CloserRequest, MatchRequest, RunStarted
from app.trace import store
from app.trace.recorder import TraceRecorder
from app.trace.runner import start_traced_run

router = APIRouter(prefix="/api", tags=["match"])


def parse_model_factory() -> ModelFactory:
    """Dependency: how a match run builds its note-parse model (tests override it)."""
    return anthropic_parse_model


@router.post("/match", response_model=RunStarted)
async def start_match(
    req: MatchRequest,
    model_factory: Annotated[ModelFactory, Depends(compile_model_factory)],
    parse_model: Annotated[ModelFactory, Depends(parse_model_factory)],
) -> RunStarted:
    """Start a match run in the background; poll `GET /api/runs/{run_id}` or stream its
    events. The compile model is only built on a compile-cache miss."""
    if not req.note and not req.fhir_bundle:
        raise HTTPException(status_code=422, detail="provide note or fhir_bundle")

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await run_match(
            rec, req, model_factory=model_factory, parse_model_factory=parse_model
        )

    # HACK(demo): DEMO_MODE=replay is not implemented yet (M7); always runs the pipeline.
    return RunStarted(run_id=start_traced_run("match", req.model_dump(mode="json"), work))


# HACK(demo): stub — fake agent steps and canned output until the LangGraph agent (M6).
async def stub_closer(rec: TraceRecorder, req: CloserRequest) -> dict[str, Any]:
    delay = get_settings().stub_event_delay_s
    async with rec.step("closer_agent", "run", {"run_id": req.run_id, "nct_id": req.nct_id}) as s:
        await asyncio.sleep(delay)
        rec.event(
            "get_unknown_criteria",
            "tool",
            input={"run_id": req.run_id, "nct": req.nct_id},
            output={"criteria": ["exc-1"]},
            note="1 unknown criterion (stub)",
        )
        await asyncio.sleep(delay)
        s.output = {
            "followups": [{"criterion_id": "exc-1", "ask": "Any DKA in the last 6 months?"}],
            "coordinator_email": "Stub email.",
            "patient_summary": {"en": "Stub summary.", "es": "Resumen de prueba."},
        }
    return {"closer": s.output}


@router.post("/closer", response_model=RunStarted)
async def start_closer(req: CloserRequest) -> RunStarted:
    if store.get_run(req.run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {req.run_id} not found")

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await stub_closer(rec, req)  # HACK(demo): stub

    # HACK(demo): stub — DEMO_MODE=replay is not implemented yet (M7); always runs the stub.

    return RunStarted(run_id=start_traced_run("closer", req.model_dump(mode="json"), work))
