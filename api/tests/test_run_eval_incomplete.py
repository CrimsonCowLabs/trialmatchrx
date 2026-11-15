"""`make eval` with a failed topic: printed, not recorded, exit 1 (fixture models, no network)."""

from typing import Any

import pytest

from app.eval.runs import latest_eval
from app.sources.trec import TrecSample
from scripts import run_eval
from tests.test_eval_matcher import Models, _parse_failing_on, _sample


def test_a_run_with_a_failed_topic_is_reported_and_not_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    models = Models()
    models.parse = _parse_failing_on("70M")  # topic 2

    def score(sample: TrecSample, **kwargs: Any) -> Any:
        return models.score(sample, **kwargs)

    monkeypatch.setattr(run_eval, "score_matcher", score)

    result = run_eval._score_matcher(_sample(), git_sha="abc", partial=False)

    out = capsys.readouterr().out
    assert not result.complete
    assert latest_eval().history == []
    assert "matcher: incomplete, NOT recorded: 1 topics failed, 0 trials could not be" in out
    assert "topic 2 failed at parse_patient: ParseFailed: malformed parse output" in out
