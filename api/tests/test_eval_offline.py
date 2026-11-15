"""`score_matcher(offline=True)`: score from the caches only, never calling a model (issue #60).
No network: the hand-built sample and fixture models of test_eval_matcher."""

from collections.abc import Callable
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.outputs import ChatResult
from sqlmodel import col, delete

from app.config import get_settings
from app.db import CompiledCriteriaRow, session_scope
from app.eval.llm_cache import SqliteLlmCache, with_cache
from app.eval.matcher import score_matcher
from app.eval.offline import (
    CacheMisses,
    CacheOnly,
    NotCached,
    offline_judge_model,
    offline_parse_model,
)
from app.pipeline.fixture_model import FixtureChatModel
from app.pipeline.judge import JudgeOutput, anthropic_judge_model
from app.pipeline.parse_patient import DraftPatient, anthropic_parse_model
from app.sources.trec import Judgment, Topic, TrecSample
from tests.test_eval_matcher import Models, Unreachable, _sample


class NeverCalled(FixtureChatModel):
    """Keys the cache like the fixture model with the same `model_name`, but fails if asked."""

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        raise AssertionError(f"{self.model_name} was called offline")


def _no_compile_model() -> Any:
    raise AssertionError("the compile model was built offline")


def _never_called(model_name: str) -> Any:
    return lambda: NeverCalled(output={"x": 1}, model_name=model_name)


async def _offline(sample: TrecSample | None = None, **kwargs: Any) -> Any:
    return await score_matcher(
        sample or _sample(),
        compile_model_factory=_no_compile_model,
        parse_model_factory=_never_called("parse-model"),
        judge_model_factory=_never_called("judge-model"),
        offline=True,
        **kwargs,
    )


async def test_offline_replays_a_fully_cached_sample_without_calling_any_model() -> None:
    live = await Models().score(_sample())

    score = await _offline()

    assert score.complete
    assert score.metrics == live.metrics
    assert score.rankings == live.rankings
    assert score.cache_misses == {"parse": 0, "compile": 0, "judge": 0}


def _with_topic_3() -> TrecSample:
    """The sample plus a third topic (judged on NCT01) that no run has parsed yet."""
    sample = _sample()
    judgment = Judgment.model_validate({"topic_id": 3, "nct_id": "NCT01", "label": 1})
    return sample.model_copy(
        update={
            "n_topics": 3,
            "topics": [*sample.topics, Topic(id=3, text="45M with hypertension, eGFR 50.")],
            "judgments": [*sample.judgments, judgment],
        }
    )


async def test_offline_on_a_partly_cached_sample_counts_the_misses_per_step() -> None:
    # A live run whose judge call failed (not cached), then NCT04's criteria leave the compile
    # cache, and the sample gains a topic nobody has parsed.
    live = Models()
    live.judge = Unreachable(output={"x": 1}, model_name="judge-model")
    await live.score(_sample())
    with session_scope() as s:
        s.exec(delete(CompiledCriteriaRow).where(col(CompiledCriteriaRow.nct_id) == "NCT04"))

    score = await _offline(_with_topic_3())

    # Topic 3's parse; NCT04's compile (judged under topics 1 and 2: one call); NCT03's judge.
    assert score.cache_misses == {"parse": 1, "compile": 1, "judge": 1}
    assert not score.complete
    (failure,) = score.failed
    assert (failure.topic_id, failure.step) == (3, "parse_patient")
    assert failure.error.startswith("NotCached: not cached")
    assert score.uncompiled == ["NCT04"]
    assert score.judge_errors == 0  # the miss is counted once, as a miss
    # What replayed is still scored: topics 1 and 2, NCT03 unknown and NCT04 last ->
    # labels [2, 2, 1, 0] (nDCG 1.0) and [1, 0, 2] (nDCG 0.5).
    assert score.rankings == {
        1: ["NCT01", "NCT03", "NCT02", "NCT04"],
        2: ["NCT01", "NCT02", "NCT04"],
    }
    assert score.metrics["ndcg@10"] == pytest.approx(0.75)


class _Seen(Exception):
    pass


class KeyRecorder(BaseCache):
    """Records the cache key of a lookup, then stops the call (nothing is sent)."""

    def __init__(self) -> None:
        self.keys: list[tuple[str, str]] = []

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        self.keys.append((prompt, llm_string))
        raise _Seen

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        raise AssertionError("unreachable")

    def clear(self, **kwargs: Any) -> None:
        pass


async def _cache_key(factory: Callable[[], BaseChatModel], schema: type) -> tuple[str, str]:
    """The `llm_cache` key a structured call (as the pipeline makes it) looks up."""
    cache = KeyRecorder()
    model = with_cache(factory, cache)()
    with pytest.raises(_Seen):
        runnable = model.with_structured_output(schema, method="json_schema")
        await runnable.ainvoke([HumanMessage("58F with type 2 diabetes, eGFR 40.")])
    (key,) = cache.keys
    return key


@pytest.mark.parametrize(
    ("live", "offline", "schema"),
    [
        (anthropic_parse_model, offline_parse_model, DraftPatient),
        (anthropic_judge_model, offline_judge_model, JudgeOutput),
    ],
)
async def test_the_offline_models_look_up_the_same_cache_key_as_the_live_ones(
    live: Callable[[], BaseChatModel],
    offline: Callable[[], BaseChatModel],
    schema: type,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-live-key")
    live_key = await _cache_key(live, schema)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)  # offline needs no key

    offline_key = await _cache_key(offline, schema)

    assert offline_key == live_key
    assert "output_config" in live_key[1]  # the bound schema is part of the key


async def test_an_offline_miss_fails_before_any_request_is_sent(
    monkeypatch: pytest.MonkeyPatch, no_api_key: None
) -> None:
    def no_request(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("ChatAnthropic tried to call the API")

    monkeypatch.setattr(ChatAnthropic, "_agenerate", no_request)
    monkeypatch.setattr(ChatAnthropic, "_generate", no_request)
    misses = CacheMisses()
    model = with_cache(offline_parse_model, CacheOnly(SqliteLlmCache(), "parse", misses))()

    with pytest.raises(NotCached, match="not cached: the parse answer"):
        await model.with_structured_output(DraftPatient, method="json_schema").ainvoke("a note")

    assert misses.counts() == {"parse": 1, "compile": 0, "judge": 0}
