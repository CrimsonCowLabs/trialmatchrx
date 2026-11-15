"""LLM judge for criteria with no predicate. Fake chat model, no network."""

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from app.pipeline.fixture_model import FixtureChatModel
from app.pipeline.judge import (
    JUDGE_CONCURRENCY,
    JudgeItem,
    judge_criteria,
    new_judge_semaphore,
)
from app.schemas import Criterion, Fact, PatientFacts, TraceEvent, Verdict
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

NCT = "NCT00000001"

TRIAL_TEXT = """Inclusion Criteria:

* Type 2 diabetes treated with metformin for at least 3 months

Exclusion Criteria:

* History of acute or chronic pancreatitis"""

NOTE = """61-year-old man with type 2 diabetes diagnosed 2014.
Meds: metformin 1000 mg twice daily. No history of pancreatitis."""

FACTS = PatientFacts(
    age=61,
    sex="male",
    conditions=[Fact(value="type 2 diabetes", date=dt.date(2014, 1, 1))],
    labs={},
    vitals={},
    meds=[Fact(value="metformin", source_span="metformin 1000 mg twice daily")],
    pregnant=None,
    smoker=None,
    lat=None,
    lon=None,
)

INC_1 = Criterion(
    id="inc-1",
    type="inclusion",
    text="Type 2 diabetes treated with metformin for at least 3 months",
    category="medication",
    predicate=None,
    needs_judgment=True,
)

GOOD: dict[str, Any] = {
    "outcome": "pass",
    "criterion_quote": "Type 2 diabetes treated with metformin for at least 3 months",
    "patient_evidence": "Meds: metformin 1000 mg twice daily.",
    "rationale": "Diagnosed 2014 and on metformin, so well over 3 months.",
}

# Missing `rationale` and an outcome outside the literal: the parser must reject it.
MALFORMED: dict[str, Any] = {"outcome": "probably", "criterion_quote": "Type 2 diabetes"}


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


def events(rec: TraceRecorder) -> list[TraceEvent]:
    return store.latest_events(rec.run_id)


def of_kind(rec: TraceRecorder, kind: str) -> list[TraceEvent]:
    return [e for e in events(rec) if e.kind == kind]


def fixture(*replies: dict[str, Any] | None) -> FixtureChatModel:
    return FixtureChatModel(replies=list(replies), tool_name="JudgeOutput", model_name="judge-fake")


async def judge_one(
    rec: TraceRecorder, model: BaseChatModel, criterion: Criterion = INC_1
) -> Verdict:
    (verdict,) = await judge_criteria(
        rec,
        [JudgeItem(nct_id=NCT, criterion=criterion, trial_text=TRIAL_TEXT)],
        FACTS,
        NOTE,
        semaphore=new_judge_semaphore(),
        model_factory=lambda: model,
    )
    return verdict


async def test_judge_returns_a_verified_llm_verdict_linked_to_its_step() -> None:
    rec = recorder()

    verdict = await judge_one(rec, fixture(GOOD))

    assert verdict.model_dump(exclude={"trace_event_id"}) == {
        "criterion_id": "inc-1",
        "outcome": "pass",
        "method": "llm",
        "criterion_quote": GOOD["criterion_quote"],
        "patient_evidence": GOOD["patient_evidence"],
        "rationale": GOOD["rationale"],
        "verified": True,
    }
    (step,) = [e for e in events(rec) if e.name == f"judge:{NCT}:inc-1"]
    assert verdict.trace_event_id == step.id
    assert step.status == "ok"
    assert step.input is not None and step.input["prompt_version"].startswith("judge-")


async def test_every_judge_call_is_traced_with_prompt_and_raw_output() -> None:
    rec = recorder()

    await judge_one(rec, fixture(GOOD))

    (llm,) = of_kind(rec, "llm")
    step_id = next(e.id for e in events(rec) if e.name == f"judge:{NCT}:inc-1")
    assert llm.parent_id == step_id
    assert llm.model == "judge-fake"
    assert llm.input is not None
    prompt = str(llm.input["messages"])
    assert INC_1.text in prompt and "metformin 1000 mg twice daily" in prompt
    assert llm.output is not None
    assert llm.output["messages"][0]["tool_calls"][0]["args"] == GOOD
    assert llm.tokens_in and llm.tokens_out


async def test_fabricated_quote_is_downgraded_to_unknown_with_a_guardrail_event() -> None:
    rec = recorder()
    fabricated = GOOD | {"patient_evidence": "Started metformin in 2019 after bariatric surgery"}

    verdict = await judge_one(rec, fixture(fabricated))

    assert verdict.outcome == "unknown"
    assert verdict.verified is False
    (guardrail,) = of_kind(rec, "guardrail")
    assert guardrail.status == "failed"
    assert guardrail.name == f"verify:{NCT}:inc-1"
    assert guardrail.output is not None
    assert guardrail.output["failed"][0]["field"] == "patient_evidence"
    assert guardrail.output["failed"][0]["quote"] == fabricated["patient_evidence"]


async def test_malformed_response_is_retried_once() -> None:
    rec = recorder()
    model = fixture(MALFORMED, GOOD)

    verdict = await judge_one(rec, model)

    assert model.calls == 2
    assert (verdict.outcome, verdict.verified) == ("pass", True)
    assert len(of_kind(rec, "llm")) == 2
    assert of_kind(rec, "error") == []


async def test_malformed_twice_becomes_unknown_with_an_error_event() -> None:
    rec = recorder()
    model = fixture(MALFORMED, None)  # bad args, then prose with no tool call

    verdict = await judge_one(rec, model)

    assert model.calls == 2
    assert verdict.outcome == "unknown"
    assert verdict.method == "llm"
    assert verdict.verified is False
    assert verdict.patient_evidence is None
    assert verdict.criterion_quote == INC_1.text
    (error,) = of_kind(rec, "error")
    assert error.name == f"judge:{NCT}:inc-1:malformed"
    assert error.output is not None and error.output["attempts"] == 2
    step = next(e for e in events(rec) if e.name == f"judge:{NCT}:inc-1")
    assert error.parent_id == step.id
    assert verdict.trace_event_id == step.id
    assert step.status == "failed"
    assert of_kind(rec, "guardrail") == []


async def test_a_model_error_becomes_unknown_with_an_error_event_without_failing_the_batch() -> (
    None
):
    class Down(FixtureChatModel):
        async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
            raise ConnectionError("api unreachable")

    rec = recorder()

    verdict = await judge_one(rec, Down(tool_name="JudgeOutput", model_name="judge-fake"))

    assert verdict.outcome == "unknown"
    (error,) = of_kind(rec, "error")
    assert error.name == f"judge:{NCT}:inc-1:error"
    assert error.output is not None and "api unreachable" in error.output["error"]


async def test_batch_keeps_input_order() -> None:
    rec = recorder()
    exc = Criterion(
        id="exc-1",
        type="exclusion",
        text="History of acute or chronic pancreatitis",
        category="history",
        predicate=None,
        needs_judgment=True,
    )
    items = [JudgeItem(NCT, c, TRIAL_TEXT) for c in (INC_1, exc)]

    verdicts = await judge_criteria(
        rec,
        items,
        FACTS,
        NOTE,
        semaphore=new_judge_semaphore(),
        model_factory=lambda: fixture(GOOD),
    )

    assert [v.criterion_id for v in verdicts] == ["inc-1", "exc-1"]


class Slow(FixtureChatModel):
    """Counts how many calls are in flight at once."""

    in_flight: int = 0
    peak: int = 0

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return self._result(messages)


async def test_one_semaphore_bounds_judge_calls_at_8_across_trials() -> None:
    rec = recorder()
    model = Slow(output=GOOD, tool_name="JudgeOutput", model_name="judge-fake")
    factory: Callable[[], BaseChatModel] = lambda: model  # noqa: E731
    semaphore = new_judge_semaphore()
    trials = [[JudgeItem(f"NCT0000000{t}", INC_1, TRIAL_TEXT) for _ in range(10)] for t in range(3)]

    results = await asyncio.gather(
        *(
            judge_criteria(rec, items, FACTS, NOTE, semaphore=semaphore, model_factory=factory)
            for items in trials
        )
    )

    assert JUDGE_CONCURRENCY == 8
    assert sum(len(r) for r in results) == 30
    assert model.calls == 30
    assert model.peak == 8
