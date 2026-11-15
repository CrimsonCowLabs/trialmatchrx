"""Eval results for the /eval page."""

from fastapi import APIRouter

from app.eval.runs import latest_eval
from app.schemas import EvalLatest

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.get("/latest", response_model=EvalLatest)
async def get_eval_latest() -> EvalLatest:
    """Latest matcher + BM25 scores on the fixed TREC sample, and every run (`make eval`)."""
    return latest_eval()
