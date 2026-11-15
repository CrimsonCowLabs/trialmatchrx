"""Compile, judge and parse ask the real ChatAnthropic for Anthropic's native structured output
(`output_config` json_schema), not a forced tool call, which claude-sonnet-5-5 can't do. The
request payload is built but never sent: no network."""

import json
import warnings
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import SecretStr

from app.pipeline.compile_criteria import compile_study
from app.pipeline.judge import JudgeItem, judge_criteria, new_judge_semaphore
from app.pipeline.parse_patient import parse_patient
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.test_compile_criteria import DRAFT, study
from tests.test_judge import FACTS, GOOD, INC_1, NCT, NOTE, TRIAL_TEXT
from tests.test_parse_patient import draft, note


class WireAnthropic(ChatAnthropic):
    """ChatAnthropic that records the request payload it would send and answers `answer` as
    JSON text, the way the API answers a json_schema request."""

    answer: dict[str, Any] = {}
    payloads: list[dict[str, Any]] = []

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.payloads.append(self._get_request_payload(messages, stop=stop, **kwargs))
        message = AIMessage(content=json.dumps(self.answer))
        return ChatResult(generations=[ChatGeneration(message=message)])


def wire(answer: dict[str, Any]) -> WireAnthropic:
    return WireAnthropic(
        model="claude-sonnet-5-5", api_key=SecretStr("x"), answer=answer, payloads=[]
    )


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


def assert_json_schema_request(model: WireAnthropic) -> None:
    (payload,) = model.payloads
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert payload["output_config"]["format"]["schema"]["type"] == "object"
    assert "tools" not in payload and "tool_choice" not in payload


def tool_warnings(caught: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    """The UserWarning ChatAnthropic gives when it can't force the tool call on this model."""
    return [w for w in caught if issubclass(w.category, UserWarning) and "tool" in str(w.message)]


async def test_compile_asks_for_a_json_schema_answer_not_a_tool_call() -> None:
    model = wire(DRAFT)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        criteria = await compile_study(study(), recorder(), model_factory=lambda: model)

    assert_json_schema_request(model)
    assert [c.text for c in criteria][-1] == "Left ventricular ejection fraction <= 40%"
    assert tool_warnings(caught) == []


async def test_judge_asks_for_a_json_schema_answer_not_a_tool_call() -> None:
    model = wire(GOOD)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        (verdict,) = await judge_criteria(
            recorder(),
            [JudgeItem(nct_id=NCT, criterion=INC_1, trial_text=TRIAL_TEXT)],
            FACTS,
            NOTE,
            semaphore=new_judge_semaphore(),
            model_factory=lambda: model,
        )

    assert_json_schema_request(model)
    assert (verdict.outcome, verdict.verified) == ("pass", True)
    assert tool_warnings(caught) == []


async def test_parse_asks_for_a_json_schema_answer_not_a_tool_call() -> None:
    model = wire(draft("demo_short"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        facts = await parse_patient(recorder(), note("demo_short"), model_factory=lambda: model)

    assert_json_schema_request(model)
    assert facts.age == 61
    assert tool_warnings(caught) == []
