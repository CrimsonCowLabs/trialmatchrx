"""BM25 scored on a TREC sample, stored in `eval_runs`, served by GET /api/eval/latest."""

from typing import Any

import pytest

from app.config import get_settings
from app.eval.runs import BM25, MATCHER, latest_eval, record_eval_run, score_bm25
from app.schemas import EvalLatest, EvalSystem
from app.sources.trec import Judgment, Topic, TrecSample, first_topics
from tests.sse import client


def _study(nct: str, text: str) -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": text},
            "eligibilityModule": {"eligibilityCriteria": "Inclusion: adults"},
        }
    }


def _sample() -> TrecSample:
    trials = {
        "NCT0A": "asthma inhaler",
        "NCT0B": "gout",
        "NCT0C": "asthma",
        "NCT0D": "acne",
        "NCT0E": "gout flare",
    }
    return TrecSample(
        seed=1,
        n_topics=2,
        per_topic=3,
        topics=[Topic(id=1, text="asthma inhaler"), Topic(id=2, text="gout")],
        judgments=[
            Judgment(topic_id=1, nct_id="NCT0A", label=2),
            Judgment(topic_id=1, nct_id="NCT0B", label=0),
            Judgment(topic_id=1, nct_id="NCT0C", label=1),
            Judgment(topic_id=2, nct_id="NCT0D", label=2),
            Judgment(topic_id=2, nct_id="NCT0E", label=0),
        ],
        trials={nct: _study(nct, text) for nct, text in trials.items()},
        dropped={"NCT0F": "not found"},
    )


def test_bm25_scores_are_the_mean_over_topics() -> None:
    # Topic 1 ranks A (2), C (1), B (0): nDCG 1.0, P@10 0.1.
    # Topic 2 ranks E (0, "gout flare") above D (2, "acne"): nDCG 1/log2(3) = 0.63093, P@10 0.1.
    # Keyword search can't exclude anyone, so it calls every judged trial eligible: right on
    # A and D (label 2), wrong on C (label 1) -> accuracy 2/3.
    assert score_bm25(_sample()) == {
        "ndcg@10": pytest.approx((1.0 + 0.6309297535714575) / 2),
        "p@10": pytest.approx(0.1),
        "accuracy": pytest.approx(2 / 3),
    }


async def test_latest_serves_the_newest_baseline_and_full_history() -> None:
    sample = _sample()
    first = record_eval_run(BM25, {"ndcg@10": 0.4, "p@10": 0.2}, sample=sample, git_sha="aaa1")
    second = record_eval_run(BM25, {"ndcg@10": 0.5, "p@10": 0.3}, sample=sample, git_sha="bbb2")

    async with client() as c:
        latest = EvalLatest.model_validate((await c.get("/api/eval/latest")).json())

    assert latest == latest_eval()
    assert latest.baseline == {"ndcg@10": 0.5, "p@10": 0.3}
    assert latest.metrics == {}  # no matcher run yet
    assert latest.sample_size == 5
    assert latest.dropped == 1
    assert [(h.id, h.system, h.git_sha) for h in latest.history] == [
        (second.id, "bm25", "bbb2"),
        (first.id, "bm25", "aaa1"),
    ]
    assert all(h.prompt_version for h in latest.history)


def test_latest_with_no_runs_is_empty() -> None:
    latest = latest_eval()

    assert (latest.metrics, latest.baseline, latest.sample_size, latest.history) == ({}, {}, 0, [])
    assert latest.compile_rate is None


def test_latest_shows_the_newest_matcher_run_and_its_compile_rate() -> None:
    sample = _sample()
    baseline = {"ndcg@10": 0.4, "p@10": 0.3, "accuracy": 0.5}
    record_eval_run(BM25, baseline, sample=sample, git_sha="a")
    matcher = {"ndcg@10": 0.6, "p@10": 0.4, "accuracy": 0.7, "compile_rate": 0.55}
    record_eval_run(MATCHER, matcher, sample=sample, git_sha="b")

    latest = latest_eval()

    assert latest.metrics == matcher
    assert latest.baseline == baseline
    assert latest.compile_rate == 0.55
    assert [h.system for h in latest.history] == ["matcher", "bm25"]


def test_latest_serves_the_compile_rate_target_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPEC.md: about 60% of criteria compile; the web page shows it, so the API serves it.
    assert latest_eval().compile_rate_target == 0.6
    monkeypatch.setattr(get_settings(), "eval_compile_rate_target", 0.75)

    assert latest_eval().compile_rate_target == 0.75


@pytest.mark.parametrize("system", [BM25, MATCHER])
def test_a_partial_sample_is_never_recorded(system: EvalSystem) -> None:
    # A score over the first N topics can't be compared with a full one.
    with pytest.raises(ValueError, match="partial sample"):
        record_eval_run(system, {"ndcg@10": 1.0}, sample=first_topics(_sample(), 1), git_sha="a")

    assert latest_eval().history == []
