"""Trial summary + compiled criteria."""

import httpx
from fastapi import APIRouter, HTTPException, Response

from app.schemas import CompileRequest, Criterion, TrialDetail
from app.sources import ctgov
from app.stub_data import STUB_CRITERIA
from app.trace.runner import traced_run

router = APIRouter(prefix="/api/trials", tags=["trials"])


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
        trial = ctgov.summarize(study)
        # HACK(demo): criteria stay empty until the compiler (issue #3) fills them from its cache.
        run.result = {"nct": nct}
    return trial


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
