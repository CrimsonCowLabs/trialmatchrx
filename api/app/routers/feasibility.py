"""Feasibility: predicates x cohort -> waterfall. No LLM: the slider calls this on every drag."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.pipeline import criteria_cache
from app.pipeline.feasibility import Cohort, InvalidOverride, simulate
from app.schemas import FeasibilityRequest, FeasibilityResult
from app.sources.cohort import get_cohort

router = APIRouter(prefix="/api/feasibility", tags=["feasibility"])


@router.post("/{nct}", response_model=FeasibilityResult)
async def run_feasibility(
    nct: str, req: FeasibilityRequest, cohort: Annotated[Cohort, Depends(get_cohort)]
) -> FeasibilityResult:
    """Waterfall of the trial's compiled criteria over the cohort. `overrides` maps a
    criterion id to a new predicate value (e.g. `{"inc-5": 45}` for eGFR >= 45).

    404 if the trial was never compiled (POST /api/trials/{nct}/compile), 503 if no cohort is
    loaded (`make seed`), 422 for an override the trial's criteria can't take."""
    if cohort.size == 0:
        raise HTTPException(503, "no cohort loaded; run `make seed`")
    criteria = criteria_cache.latest(nct)
    if not criteria:
        raise HTTPException(404, f"{nct} has no compiled criteria; compile it first")
    try:
        return simulate(nct, criteria, cohort, req.overrides)
    except InvalidOverride as exc:
        raise HTTPException(422, str(exc)) from exc
