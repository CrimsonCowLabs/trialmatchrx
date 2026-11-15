"""Feasibility: predicates x cohort -> waterfall."""

from fastapi import APIRouter

from app.schemas import FeasibilityRequest, FeasibilityResult
from app.stub_data import stub_feasibility

router = APIRouter(prefix="/api/feasibility", tags=["feasibility"])


@router.post("/{nct}", response_model=FeasibilityResult)
async def run_feasibility(nct: str, req: FeasibilityRequest) -> FeasibilityResult:
    # HACK(demo): stub — fake waterfall until feasibility.py + the cohort land (M5).
    override = req.overrides.get("inc-1", 45)
    egfr_min = float(override) if isinstance(override, int | float) else 45.0
    return stub_feasibility(nct, egfr_min)
