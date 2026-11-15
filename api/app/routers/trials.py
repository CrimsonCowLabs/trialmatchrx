"""Trial summary + compiled criteria."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from app.pipeline import criteria_cache
from app.pipeline.compile_criteria import (
    CompileModelUnavailable,
    ModelFactory,
    anthropic_compile_model,
    compile_study,
)
from app.pipeline.study_source import StudyNotFound, load_study
from app.schemas import CompileRequest, Criterion, TrialDetail
from app.sources import ctgov
from app.trace.runner import traced_run

router = APIRouter(prefix="/api/trials", tags=["trials"])


def compile_model_factory() -> ModelFactory:
    """Dependency: how the compile route builds its model (tests override it)."""
    return anthropic_compile_model


@router.get("/{nct}", response_model=TrialDetail)
async def get_trial(nct: str, response: Response) -> TrialDetail:
    """Cached trial summary (fetched once on a cache miss). Traced as a `trial` run whose id
    comes back in the `X-Run-Id` header, on errors too."""
    async with traced_run("trial", {"nct": nct}) as run:
        response.headers["X-Run-Id"] = run.run_id
        headers = {"X-Run-Id": run.run_id}
        try:
            study = await ctgov.get_study(nct, recorder=run.recorder)
        except ctgov.StudyNotFoundError as exc:
            raise HTTPException(404, f"{nct} not found on ClinicalTrials.gov", headers) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"ClinicalTrials.gov: {exc}", headers) from exc
        trial = ctgov.summarize(study).model_copy(update={"criteria": criteria_cache.latest(nct)})
        run.result = {"nct": nct}
    return trial


@router.post("/{nct}/compile", response_model=list[Criterion])
async def compile_trial(
    nct: str,
    req: CompileRequest,
    response: Response,
    model_factory: Annotated[ModelFactory, Depends(compile_model_factory)],
) -> list[Criterion]:
    """Traced: the compile run's id comes back in the `X-Run-Id` header."""
    async with traced_run("compile", {"nct": nct, "force": req.force}) as run:
        response.headers["X-Run-Id"] = run.run_id
        try:
            study = await load_study(nct, recorder=run.recorder)
            criteria = await compile_study(
                study, run.recorder, model_factory=model_factory, force=req.force
            )
        except StudyNotFound as exc:
            raise HTTPException(404, f"trial {nct} not found") from exc
        except CompileModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        run.result = {"criteria": [c.model_dump(mode="json") for c in criteria]}
    return criteria
