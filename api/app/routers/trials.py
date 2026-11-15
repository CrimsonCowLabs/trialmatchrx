"""Trial summary + compiled criteria."""

from fastapi import APIRouter, Response

from app.schemas import CompileRequest, Criterion, TrialDetail
from app.stub_data import STUB_CRITERIA, STUB_TRIAL
from app.trace.runner import traced_run

router = APIRouter(prefix="/api/trials", tags=["trials"])


@router.get("/{nct}", response_model=TrialDetail)
async def get_trial(nct: str) -> TrialDetail:
    # HACK(demo): stub — same fake trial for every NCT id until the ctgov cache lands (M1).
    return STUB_TRIAL.model_copy(update={"nct_id": nct})


@router.post("/{nct}/compile", response_model=list[Criterion])
async def compile_trial(nct: str, req: CompileRequest, response: Response) -> list[Criterion]:
    """Traced: the compile run's id comes back in the `X-Run-Id` header."""
    async with traced_run("compile", {"nct": nct, "force": req.force}) as run:
        response.headers["X-Run-Id"] = run.run_id
        async with run.recorder.step("compile_criteria", "step", {"nct": nct}) as s:
            # HACK(demo): stub — canned criteria until compile_criteria.py lands (M1).
            criteria = STUB_CRITERIA
            s.output = {"criteria": len(criteria)}
            s.cache_hit = not req.force
        run.result = {"criteria": [c.model_dump(mode="json") for c in criteria]}
    return criteria
