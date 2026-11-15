"""scripts/run_eval.py --offline and --fail-fast (issue #60). No network and no API key: the
hand-built sample from test_eval_matcher saved to a temp file, its fixture models, and the
offline path's cache-only models."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.eval.runs import latest_eval
from app.sources import trec
from app.sources.trec import TrecSample
from scripts import run_eval
from tests.test_eval_matcher import Models, Unreachable, _sample


@pytest.fixture
def saved_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`_sample()` as data/fixtures/trec/sample.json, no API key, fixture models."""
    path = tmp_path / "sample.json"
    trec.save_sample(_sample(), path)
    monkeypatch.setattr(trec, "SAMPLE_PATH", path)
    load = trec.load_sample  # its default path was bound before SAMPLE_PATH was patched
    monkeypatch.setattr(trec, "load_sample", lambda: load(path))
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)

    def score(sample: TrecSample, **kwargs: Any) -> Any:
        return Models().score(sample, **kwargs)

    monkeypatch.setattr(run_eval, "score_matcher", score)
    yield


def _systems() -> list[str]:
    return sorted(h.system for h in latest_eval().history)


async def _warm_cache() -> None:
    """A complete live run: every answer of the sample is cached."""
    await Models().score(_sample())


def test_offline_runs_the_matcher_without_an_api_key_and_records_a_full_replay(
    saved_sample: None, capsys: pytest.CaptureFixture[str]
) -> None:

    asyncio.run(_warm_cache())

    run_eval.main(rebuild=False, bm25_only=False, offline=True)

    out = capsys.readouterr().out
    assert "matcher: offline" in out
    assert "skipped" not in out
    # Same score as the live run (test_matcher_scores_the_sample_by_hand).
    assert "matcher     0.7500    0.1500    0.8000" in out
    assert _systems() == ["bm25", "matcher"]


def test_offline_on_a_cold_cache_reports_the_misses_records_nothing_and_exits_1(
    saved_sample: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        run_eval.main(rebuild=False, bm25_only=False, offline=True)

    assert exit_.value.code == 1
    out = capsys.readouterr().out
    # Both topics' parses miss; the compile cache is checked for every trial even so. The
    # judge calls depend on the parsed facts, so they can't be counted.
    assert "cache misses (would call the API): parse 2, compile 4, judge 0" in out
    assert "matcher: incomplete, NOT recorded: 2 topics failed" in out
    assert _systems() == []


def test_fail_fast_prints_where_it_stopped_records_nothing_and_exits_1(
    saved_sample: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    models = Models()
    models.judge = Unreachable(output={"x": 1}, model_name="judge-model")

    def score(sample: TrecSample, **kwargs: Any) -> Any:
        return models.score(sample, **kwargs)

    monkeypatch.setattr(run_eval, "score_matcher", score)

    with pytest.raises(SystemExit) as exit_:
        run_eval.main(rebuild=False, bm25_only=False, fail_fast=True)

    assert exit_.value.code == 1
    out = capsys.readouterr().out
    assert (
        "matcher: stopped (--fail-fast) at judge, topic 1, trial NCT03: "
        "ConnectionError: api unreachable" in out
    )
    assert _systems() == []  # neither the matcher nor BM25


def test_offline_fail_fast_stops_at_the_first_miss(
    saved_sample: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        run_eval.main(rebuild=False, bm25_only=False, offline=True, fail_fast=True)

    assert exit_.value.code == 1
    out = capsys.readouterr().out
    assert "matcher: stopped (--fail-fast) at parse, topic 1: NotCached: not cached" in out
    assert _systems() == []


def test_the_command_line_takes_both_flags() -> None:
    args = run_eval.parse_args(["--offline", "--fail-fast"])

    assert (args.offline, args.fail_fast) == (True, True)
