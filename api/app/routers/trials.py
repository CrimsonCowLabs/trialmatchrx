"""Trial summary + compiled criteria."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth.deps import signed_in_user
from app.db import UserRow
from app.pipeline import criteria_cache
from app.pipeline.access_barriers import flag_access_barriers
from app.pipeline.compile_criteria import (
    CompileFailed,
    CompileModelUnavailable,
    ModelFactory,
    anthropic_compile_model,
    compile_study,
)
from app.schemas import CompileRequest, Criterion, TrialDetail, TrialListItem
from app.sources import ctgov
from app.trace.runner import traced_run

router = APIRouter(prefix="/api/trials", tags=["trials"])


def compile_model_factory() -> ModelFactory:
    """Dependency: how the compile route builds its model (tests override it)."""
    return anthropic_compile_model


@router.get("", response_model=list[TrialListItem])
async def list_trials(q: str | None = None) -> list[TrialListItem]:
    """Every cached trial (newest version per NCT ID), sorted by NCT ID; `q` is a
    case-insensitive substring match on NCT ID or title. A plain read of the trials and compile
    caches: no network, and not a traced run (it would add a run on every page view)."""
    needle = (q or "").strip().lower()
    items = []
    for study in ctgov.cached_studies():
        trial = ctgov.summarize(study)
        if needle and needle not in trial.nct_id.lower() and needle not in trial.title.lower():
            continue
        criteria = criteria_cache.latest(trial.nct_id)
        items.append(
            TrialListItem(
                nct_id=trial.nct_id,
                title=trial.title,
                phase=trial.phase,
                overall_status=trial.overall_status,
                compiled=bool(criteria),
                criteria_count=len(criteria),
            )
        )
    return sorted(items, key=lambda item: item.nct_id)


@router.get("/{nct}", response_model=TrialDetail)
async def get_trial(
    nct: str, response: Response, user: Annotated[UserRow, Depends(signed_in_user)]
) -> TrialDetail:
    """Cached trial summary (fetched once on a cache miss). Traced as a `trial` run whose id
    comes back in the `X-Run-Id` header, on errors too."""
    async with traced_run("trial", {"nct": nct}, created_by=user.id) as run:
        response.headers["X-Run-Id"] = run.run_id
        headers = {"X-Run-Id": run.run_id}
        try:
            study = await ctgov.get_study(nct, recorder=run.recorder)
        except ctgov.StudyNotFoundError as exc:
            raise HTTPException(404, f"{nct} not found on ClinicalTrials.gov", headers) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"ClinicalTrials.gov: {exc}", headers) from exc
        trial = ctgov.summarize(study)
        criteria = criteria_cache.latest(trial.nct_id)
        if criteria:
            criteria = await flag_access_barriers(trial.nct_id, criteria, run.recorder)
        trial.criteria = criteria
        run.result = {"nct": nct}
    return trial


@router.post("/{nct}/compile", response_model=list[Criterion])
async def compile_trial(
    nct: str,
    req: CompileRequest,
    response: Response,
    model_factory: Annotated[ModelFactory, Depends(compile_model_factory)],
    user: Annotated[UserRow, Depends(signed_in_user)],
) -> list[Criterion]:
    """Traced: the compile run's id comes back in the `X-Run-Id` header."""
    request = {"nct": nct, "force": req.force}
    async with traced_run("compile", request, created_by=user.id) as run:
        response.headers["X-Run-Id"] = run.run_id
        headers = {"X-Run-Id": run.run_id}
        try:
            study = await ctgov.get_study(nct, recorder=run.recorder)
            criteria = await compile_study(
                study, run.recorder, model_factory=model_factory, force=req.force
            )
        except ctgov.StudyNotFoundError as exc:
            raise HTTPException(404, f"{nct} not found on ClinicalTrials.gov", headers) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"ClinicalTrials.gov: {exc}", headers) from exc
        except CompileModelUnavailable as exc:
            raise HTTPException(503, str(exc), headers) from exc
        except CompileFailed as exc:
            raise HTTPException(502, str(exc), headers) from exc
        run.result = {"criteria": [c.model_dump(mode="json") for c in criteria]}
    return criteria
