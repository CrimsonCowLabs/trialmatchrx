"""Eval results for the /eval page."""

from fastapi import APIRouter

from app.schemas import EvalLatest
from app.stub_data import STUB_EVAL

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.get("/latest", response_model=EvalLatest)
async def get_eval_latest() -> EvalLatest:
    # HACK(demo): stub — zeros until run_eval.py writes eval_runs (M4).
    return STUB_EVAL
