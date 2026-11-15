"""Scoring the fixed TREC sample and the `eval_runs` history behind GET /api/eval/latest.

    metrics = score_bm25(sample)                       # {"ndcg@10": ..., "p@10": ...}
    row = record_eval_run(BM25, metrics, sample=sample, git_sha=current_git_sha())
    latest_eval()                                      # EvalLatest for the /eval page

Each topic reranks only its own judged trials (about 20); scores are the mean over topics.
"""

import subprocess
import uuid
from statistics import fmean

from sqlmodel import col, select

from app.config import REPO_DIR
from app.db import EvalRunRow, session_scope
from app.eval.bm25 import Bm25Index, trial_text
from app.eval.metrics import ndcg_at_k, precision_at_k
from app.prompts import load_prompt
from app.schemas import EvalLatest, EvalRunSummary, EvalSystem
from app.sources.trec import TrecSample

BM25: EvalSystem = "bm25"
MATCHER: EvalSystem = "matcher"
K = 10
# The prompts a matcher run depends on. Every row records them, BM25 included, so the history
# lines up baseline and matcher rows by prompt version.
EVAL_PROMPTS = ("parse_patient", "compile_criteria", "judge")


def score_bm25(sample: TrecSample) -> dict[str, float]:
    """Mean nDCG@10 and P@10 of BM25 over the sample's topics (label 2 = relevant)."""
    index = Bm25Index({nct: trial_text(study) for nct, study in sample.trials.items()})
    ndcgs, precisions = [], []
    for topic in sample.topics:
        labels = {j.nct_id: j.label for j in sample.judgments if j.topic_id == topic.id}
        ranked = [labels[nct] for nct in index.rank(topic.text, list(labels))]
        ndcgs.append(ndcg_at_k(ranked, K))
        precisions.append(precision_at_k(ranked, K))
    return {f"ndcg@{K}": fmean(ndcgs), f"p@{K}": fmean(precisions)}


def current_git_sha() -> str | None:
    """Short HEAD SHA, suffixed `-dirty` when the tree has uncommitted changes; None outside
    a git checkout."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}-dirty" if dirty else sha


def current_prompt_version() -> str:
    """e.g. `parse-patient-v1+compile-criteria-v1+judge-v1`."""
    return "+".join(load_prompt(name).version for name in EVAL_PROMPTS)


def record_eval_run(
    system: EvalSystem,
    metrics: dict[str, float],
    *,
    sample: TrecSample,
    git_sha: str | None,
) -> EvalRunRow:
    row = EvalRunRow(
        id=uuid.uuid4().hex,
        system=system,
        git_sha=git_sha,
        prompt_version=current_prompt_version(),
        sample_size=sample.sample_size,
        topics=len(sample.topics),
        dropped=len(sample.dropped),
        metrics=metrics,
    )
    with session_scope() as s:
        s.add(row)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row


def _summary(row: EvalRunRow) -> EvalRunSummary:
    return EvalRunSummary(
        id=row.id,
        created_at=row.created_at,
        system=MATCHER if row.system == MATCHER else BM25,
        git_sha=row.git_sha,
        prompt_version=row.prompt_version,
        sample_size=row.sample_size,
        metrics=row.metrics,
    )


def latest_eval() -> EvalLatest:
    """The newest matcher and BM25 scores, sample size from the newest run, every run newest
    first. Empty (zeros, `{}`) before the first `make eval`."""
    with session_scope() as s:
        rows = s.exec(select(EvalRunRow).order_by(col(EvalRunRow.created_at).desc())).all()
        newest = rows[0] if rows else None
        matcher = next((r for r in rows if r.system == MATCHER), None)
        baseline = next((r for r in rows if r.system == BM25), None)
        return EvalLatest(
            metrics=matcher.metrics if matcher else {},
            baseline=baseline.metrics if baseline else {},
            compile_rate=None,  # HACK(demo): the matcher eval (#11) reports the compile rate
            sample_size=newest.sample_size if newest else 0,
            topics=newest.topics if newest else 0,
            dropped=newest.dropped if newest else 0,
            history=[_summary(r) for r in rows],
        )
