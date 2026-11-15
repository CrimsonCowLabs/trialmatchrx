"""POST /api/match and POST /api/closer: start a background run, return its id."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.pipeline.closer_agent import (
    CloserModelUnavailable,
    CloserToolError,
    MatchRunNotFinished,
    anthropic_closer_model,
    find_trial_match,
    run_closer,
)
from app.pipeline.compile_criteria import ModelFactory
from app.pipeline.judge import anthropic_judge_model
from app.pipeline.match_run import run_match
from app.pipeline.parse_patient import anthropic_parse_model
from app.routers.trials import compile_model_factory
from app.schemas import CloserRequest, MatchRequest, RunStarted
from app.sources import synthea
from app.trace.recorder import TraceRecorder
from app.trace.runner import start_traced_run

router = APIRouter(prefix="/api", tags=["match"])


def parse_model_factory() -> ModelFactory:
    """Dependency: how a match run builds its note-parse model (tests override it)."""
    return anthropic_parse_model


def judge_model_factory() -> ModelFactory:
    """Dependency: how a match run builds its judge model (tests override it)."""
    return anthropic_judge_model


@router.post("/match", response_model=RunStarted)
async def start_match(
    req: MatchRequest,
    model_factory: Annotated[ModelFactory, Depends(compile_model_factory)],
    parse_model: Annotated[ModelFactory, Depends(parse_model_factory)],
    judge_model: Annotated[ModelFactory, Depends(judge_model_factory)],
) -> RunStarted:
    """Start a match run in the background; poll `GET /api/runs/{run_id}` or stream its
    events. Exactly one of `note` (parsed by the LLM) or `fhir_bundle` (a Synthea FHIR bundle,
    mapped in code) is required. The compile model is only built on a compile-cache miss."""
    if bool(req.note) == (req.fhir_bundle is not None):
        raise HTTPException(status_code=422, detail="provide exactly one of note or fhir_bundle")
    if req.fhir_bundle is not None:
        try:
            synthea.check_bundle(req.fhir_bundle)
        except synthea.InvalidBundle as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await run_match(
            rec,
            req,
            model_factory=model_factory,
            parse_model_factory=parse_model,
            judge_model_factory=judge_model,
        )

    # HACK(demo): DEMO_MODE=replay is not implemented yet (M7); always runs the pipeline.
    return RunStarted(run_id=start_traced_run("match", req.model_dump(mode="json"), work))


def closer_model_factory() -> ModelFactory:
    """Dependency: how a closer run builds its agent model (tests override it)."""
    return anthropic_closer_model


@router.post("/closer", response_model=RunStarted)
async def start_closer(
    req: CloserRequest,
    model_factory: Annotated[ModelFactory, Depends(closer_model_factory)],
) -> RunStarted:
    """Start the closer agent on one trial of a finished match run; stream it like a match.
    404 if the run or the trial isn't there, 409 while the match is still running, 503 with
    no API key."""
    try:
        find_trial_match(req.run_id, req.nct_id)
    except MatchRunNotFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CloserToolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        model = model_factory()
    except CloserModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def work(rec: TraceRecorder) -> dict[str, Any]:
        return await run_closer(rec, req, model=model)

    # HACK(demo): DEMO_MODE=replay is not implemented yet (M7); always runs the agent.
    return RunStarted(run_id=start_traced_run("closer", req.model_dump(mode="json"), work))
