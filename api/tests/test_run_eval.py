"""scripts/run_eval.py --topics N: a partial run on the first N topics, reported as partial and
never recorded. No network: the sample is the hand-built one from test_eval_matcher, saved to a
temp file, and the matcher runs on its fixture models."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import get_settings
from app.eval.runs import latest_eval
from app.sources import trec
from scripts import run_eval
from tests.test_eval_matcher import Models, _sample


@pytest.fixture
def saved_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`_sample()` as data/fixtures/trec/sample.json, an API key set, fixture models."""
    path = tmp_path / "sample.json"
    trec.save_sample(_sample(), path)
    monkeypatch.setattr(trec, "SAMPLE_PATH", path)
    load = trec.load_sample  # its default path was bound before SAMPLE_PATH was patched
    monkeypatch.setattr(trec, "load_sample", lambda: load(path))
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    monkeypatch.setattr(run_eval, "score_matcher", lambda sample: Models().score(sample))
    yield


def test_a_partial_run_reports_both_systems_over_n_topics_and_records_nothing(
    saved_sample: None, capsys: pytest.CaptureFixture[str]
) -> None:
    run_eval.main(rebuild=False, bm25_only=False, topics=1)

    out = capsys.readouterr().out
    assert "partial run: 1 of 2 topics" in out
    # Topic 1 alone. Matcher: labels [2, 2, 1, 0] -> nDCG 1.0, P@10 0.2, accuracy 3/3.
    assert "matcher     1.0000    0.2000    1.0000" in out
    # BM25 calls every trial eligible: accuracy 2/3 (NCT02, label 1, is wrong).
    assert "bm25" in out and "0.6667" in out
    assert latest_eval().history == []  # complete, but partial: no eval_runs row


def test_a_full_run_still_records_both_systems(saved_sample: None) -> None:
    run_eval.main(rebuild=False, bm25_only=False, topics=None)

    assert sorted(h.system for h in latest_eval().history) == ["bm25", "matcher"]


@pytest.mark.parametrize("n", [0, -2, 3])
def test_an_out_of_range_topic_count_is_rejected(saved_sample: None, n: int) -> None:
    with pytest.raises(SystemExit, match=r"--topics must be between 1 and 2"):
        run_eval.main(rebuild=False, bm25_only=False, topics=n)

    assert latest_eval().history == []


def test_topics_covering_the_whole_sample_is_still_partial_and_unrecorded(
    saved_sample: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # Any --topics run is never recorded (issue #61), even when N is every topic.
    run_eval.main(rebuild=False, bm25_only=False, topics=2)

    assert "partial run: 2 of 2 topics" in capsys.readouterr().out
    assert latest_eval().history == []


@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_the_command_line_rejects_a_topic_count_below_one(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Before main runs, so a --rebuild never fetches anything first.
    with pytest.raises(SystemExit):
        run_eval.parse_args(["--rebuild", f"--topics={value}"])

    assert "argument --topics: must be" in capsys.readouterr().err
