"""Scoring the fixed TREC sample and the `eval_runs` history behind GET /api/eval/latest.

    metrics = score_bm25(sample)                       # {"ndcg@10": ..., "p@10": ...}
    row = record_eval_run(BM25, metrics, sample=sample, git_sha=current_git_sha())
    latest_eval()                                      # EvalLatest for the /eval page

Each topic reranks only its own judged trials (about 20); scores are the mean over topics.
"""

import subprocess
import uuid
from collections.abc import Callable
from statistics import fmean

from sqlmodel import col, select

from app.config import REPO_DIR
from app.db import EvalRunRow, session_scope
from app.eval.bm25 import Bm25Index, trial_text
from app.eval.metrics import eligibility_accuracy, ndcg_at_k, precision_at_k
from app.prompts import load_prompt
from app.schemas import EvalLatest, EvalRunSummary, EvalSystem
from app.sources.trec import TrecSample

BM25: EvalSystem = "bm25"
MATCHER: EvalSystem = "matcher"
K = 10
ACCURACY = "accuracy"  # eligible vs excluded, labels 1 and 2 only
COMPILE_RATE = "compile_rate"  # matcher rows only: share of criteria with a predicate
# The prompts a matcher run depends on. Every row records them, BM25 included, so the history
# lines up baseline and matcher rows by prompt version.
EVAL_PROMPTS = ("parse_patient", "compile_criteria", "judge")


def topic_labels(sample: TrecSample, topic_id: int) -> dict[str, int]:
    """NCT ID -> qrels label for one topic's judged trials."""
    return {j.nct_id: j.label for j in sample.judgments if j.topic_id == topic_id}


def score_rankings(
    sample: TrecSample,
    rankings: dict[int, list[str]],
    called_eligible: Callable[[int, str], bool],
) -> dict[str, float]:
    """Mean nDCG@10 and P@10 over topics (each topic's judged trials, best first), and
    eligible-vs-excluded accuracy pooled over every label 1 / 2 pair."""
    ndcgs, precisions, calls = [], [], []
    for topic in sample.topics:
        labels = topic_labels(sample, topic.id)
        ranked = [labels[nct] for nct in rankings[topic.id]]
        ndcgs.append(ndcg_at_k(ranked, K))
        precisions.append(precision_at_k(ranked, K))
        calls += [(label, called_eligible(topic.id, nct)) for nct, label in labels.items()]
    metrics = {f"ndcg@{K}": fmean(ndcgs), f"p@{K}": fmean(precisions)}
    accuracy = eligibility_accuracy(calls)
    if accuracy is not None:
        metrics[ACCURACY] = accuracy
    return metrics


def score_bm25(sample: TrecSample) -> dict[str, float]:
    """BM25's nDCG@10, P@10 and accuracy on the sample (label 2 = relevant). Keyword search has
    no notion of exclusion, so it calls every judged trial it ranks eligible."""
    index = Bm25Index({nct: trial_text(study) for nct, study in sample.trials.items()})
    rankings = {t.id: index.rank(t.text, list(topic_labels(sample, t.id))) for t in sample.topics}
    return score_rankings(sample, rankings, lambda topic_id, nct: True)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, text=True, check=True
    ).stdout.strip()


def current_git_sha() -> str | None:
    """Short HEAD SHA, suffixed `-dirty` when the tree has uncommitted changes; None outside
    a git checkout. Take it before the eval writes anything into the tree."""
    try:
        sha, dirty = _git("rev-parse", "--short", "HEAD"), _git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}-dirty" if dirty else sha


def current_prompt_version() -> str:
    """e.g. `parse-patient-v3+compile-criteria-v2+judge-v2`."""
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
            compile_rate=matcher.metrics.get(COMPILE_RATE) if matcher else None,
            sample_size=newest.sample_size if newest else 0,
            topics=newest.topics if newest else 0,
            dropped=newest.dropped if newest else 0,
            history=[EvalRunSummary.model_validate(r, from_attributes=True) for r in rows],
        )
