"""`score_matcher(fail_fast=True)`: stop at the first model failure (issue #60). No network: the
hand-built sample and fixture models of test_eval_matcher. Topic 1 is matched first, its trials
in NCT order (NCT01..NCT04; NCT03 is the judged one); topic 2 after it."""

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from sqlmodel import col, delete

from app.db import CompiledCriteriaRow, session_scope
from app.trace import store
from tests.test_eval_matcher import (
    CRITERIA,
    ByMarker,
    Models,
    Unreachable,
    _parse_failing_on,
    _sample,
)


class Counting(ByMarker):
    """The fixture compile model, remembering which trials it was asked to compile."""

    asked: list[str] = []

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        prompt = "".join(str(m.content) for m in messages)
        self.asked.append(next(nct for nct in CRITERIA if nct in prompt))
        return super()._result(messages)


def _models() -> Models:
    models = Models()
    models.compile = Counting(
        output={"criteria": []},
        by_marker={n: {"criteria": [c]} for n, c in CRITERIA.items()},
        asked=[],
    )
    return models


def _trials_run(run_id: str) -> list[str]:
    return [
        e.name.removeprefix("trial:")
        for e in store.latest_events(run_id)
        if e.kind == "step" and e.name.startswith("trial:")
    ]


async def test_fail_fast_stops_at_a_judge_error_before_any_later_trial_or_topic() -> None:
    models = _models()
    models.judge = Unreachable(output={"x": 1}, model_name="judge-model")

    score = await models.score(_sample(), fail_fast=True)

    stop = score.stopped
    assert stop is not None
    assert (stop.step, stop.topic_id, stop.nct_id) == ("judge", 1, "NCT03")
    assert stop.error == "ConnectionError: api unreachable"
    assert stop.run_id == score.run_ids[1]
    run = store.get_run(stop.run_id)
    assert run is not None and run.status == "failed"
    assert run.error == "ConnectionError: api unreachable"  # the cause, not the cancel
    assert not score.complete
    # NCT04 (after NCT03) was never compiled or started, and topic 2 never ran.
    assert models.compile.asked == ["NCT01", "NCT02", "NCT03"]  # type: ignore[attr-defined]
    assert _trials_run(score.run_ids[1]) == ["NCT01", "NCT02", "NCT03"]
    assert sorted(score.run_ids) == [1]
    assert models.parse.calls == 1


async def test_fail_fast_stops_at_a_failed_parse_before_the_next_topic() -> None:
    models = _models()
    models.parse = _parse_failing_on("58F")  # topic 1

    score = await models.score(_sample(), fail_fast=True)

    stop = score.stopped
    assert stop is not None
    assert (stop.step, stop.topic_id, stop.nct_id) == ("parse", 1, None)
    assert stop.error.startswith("ParseFailed: malformed parse output")
    assert sorted(score.run_ids) == [1]
    assert models.compile.asked == []  # type: ignore[attr-defined]


async def test_fail_fast_stops_at_a_trial_that_cannot_compile() -> None:
    models = _models()
    models.compile.by_marker["NCT02"] = {"criteria": "not a list"}  # type: ignore[attr-defined]

    score = await models.score(_sample(), fail_fast=True)

    stop = score.stopped
    assert stop is not None
    assert (stop.step, stop.topic_id, stop.nct_id) == ("compile", 1, "NCT02")
    assert stop.error.startswith("CompileFailed: NCT02: malformed compile output")
    assert models.compile.asked == ["NCT01", "NCT02"]  # type: ignore[attr-defined]
    assert sorted(score.run_ids) == [1]


async def test_without_fail_fast_the_same_failure_is_collected_and_the_run_carries_on() -> None:
    models = _models()
    models.judge = Unreachable(output={"x": 1}, model_name="judge-model")

    score: Any = await models.score(_sample())

    assert score.stopped is None
    assert score.judge_errors == 1
    assert sorted(score.run_ids) == [1, 2]


async def test_offline_fail_fast_stops_at_the_first_cache_miss() -> None:
    await Models().score(_sample())  # everything cached ...
    with session_scope() as s:  # ... but NCT02's criteria
        s.exec(delete(CompiledCriteriaRow).where(col(CompiledCriteriaRow.nct_id) == "NCT02"))
    models = _models()

    score = await models.score(_sample(), offline=True, fail_fast=True)

    stop = score.stopped
    assert stop is not None
    assert (stop.step, stop.topic_id, stop.nct_id) == ("compile", 1, "NCT02")
    assert stop.error.startswith("CompileNotCached: not cached: the compile answer")
    assert _trials_run(score.run_ids[1]) == ["NCT01", "NCT02"]
    assert sorted(score.run_ids) == [1]
    assert models.calls == (0, 0, 0)


async def test_offline_fail_fast_on_a_cold_cache_stops_at_the_first_parse() -> None:
    models = _models()

    score = await models.score(_sample(), offline=True, fail_fast=True)

    stop = score.stopped
    assert stop is not None
    assert (stop.step, stop.topic_id, stop.nct_id) == ("parse", 1, None)
    assert stop.error.startswith("NotCached: not cached: the parse answer")
    assert sorted(score.run_ids) == [1]
    assert models.calls == (0, 0, 0)


async def test_a_stop_at_a_judge_error_keeps_the_answers_already_paid_for() -> None:
    # Without --fail-fast this topic would finish and cache its answers, so a stop keeps them:
    # the re-run asks only for the call that failed.
    models = _models()
    models.judge = Unreachable(output={"x": 1}, model_name="judge-model")
    await models.score(_sample(), fail_fast=True)

    again = Models()
    await again.score(_sample())

    assert again.calls == (1, 1, 1)  # NCT04 (never reached), topic 2's parse, NCT03's judge


async def test_a_stop_at_a_failed_parse_caches_nothing_of_that_topic() -> None:
    models = _models()
    models.parse = _parse_failing_on("58F")
    await models.score(_sample(), fail_fast=True)

    again = Models()
    await again.score(_sample())

    assert again.calls == (4, 2, 1)
