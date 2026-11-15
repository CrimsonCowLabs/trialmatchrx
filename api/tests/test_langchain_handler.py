"""The LangChain callback handler turns llm/tool calls into trace events. No network."""

from collections.abc import Iterator

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import tool

from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder


def fake_model(*replies: BaseMessage) -> GenericFakeChatModel:
    messages: Iterator[BaseMessage] = iter(replies)
    return GenericFakeChatModel(messages=messages)


@pytest.fixture
def rec() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


async def test_chat_model_call_becomes_an_llm_event(rec: TraceRecorder) -> None:
    model = fake_model(
        AIMessage(
            "eGFR is 48",
            usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
        )
    )

    async with rec.step("parse_patient") as parent:
        await model.ainvoke("What is the eGFR?", config={"callbacks": [rec.langchain_handler()]})

    events = store.load_events(rec.run_id)
    llm = [e for e in events if e.kind == "llm"]
    assert [e.status for e in llm] == ["started", "ok"]
    started, done = llm
    assert started.id == done.id
    assert done.parent_id == parent.id
    assert started.input is not None
    assert started.input["messages"][0][0]["content"] == "What is the eGFR?"
    assert done.output is not None and done.output["text"] == "eGFR is 48"
    assert (done.tokens_in, done.tokens_out) == (12, 4)
    assert done.model == "GenericFakeChatModel"
    assert done.ended_at is not None


async def test_metadata_parent_id_overrides_the_current_step(rec: TraceRecorder) -> None:
    model = fake_model(AIMessage("ok"))

    await model.ainvoke(
        "hi",
        config={
            "callbacks": [rec.langchain_handler()],
            "metadata": {"run_id": rec.run_id, "parent_id": "criterion-evt"},
        },
    )

    assert {e.parent_id for e in store.load_events(rec.run_id)} == {"criterion-evt"}


async def test_llm_error_marks_the_event_failed(rec: TraceRecorder) -> None:
    model = fake_model()  # exhausted iterator -> the model raises

    with pytest.raises(Exception):  # noqa: B017 - whatever the fake raises
        await model.ainvoke("hi", config={"callbacks": [rec.langchain_handler()]})

    final = store.latest_events(rec.run_id)[-1]
    assert final.kind == "llm"
    assert final.status == "failed"
    assert final.output is not None and "error" in final.output


async def test_tool_call_becomes_a_tool_event(rec: TraceRecorder) -> None:
    @tool
    async def get_trial_contacts(nct: str) -> str:
        """Look up trial contacts."""
        return f"contacts for {nct}"

    await get_trial_contacts.ainvoke(
        {"nct": "NCT01"}, config={"callbacks": [rec.langchain_handler()]}
    )

    started, done = store.load_events(rec.run_id)
    assert (started.kind, started.name, started.status) == ("tool", "get_trial_contacts", "started")
    assert started.input is not None and started.input["nct"] == "NCT01"
    assert done.status == "ok"
    assert done.output == {"result": "contacts for NCT01"}


class PricedFakeChatModel(GenericFakeChatModel):
    model_name: str = "claude-sonnet-4-5"


def _usage(tokens_in: int, tokens_out: int) -> AIMessage:
    return AIMessage(
        "ok",
        usage_metadata={
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    )


async def test_llm_event_cost_comes_from_the_price_table(rec: TraceRecorder) -> None:
    model = PricedFakeChatModel(messages=iter([_usage(1000, 500)]))

    await model.ainvoke("hi", config={"callbacks": [rec.langchain_handler()]})

    done = store.latest_events(rec.run_id)[-1]
    assert done.model == "claude-sonnet-4-5"
    assert done.cost_usd == pytest.approx(0.003 + 0.0075)  # $3 / MTok in, $15 / MTok out


async def test_unpriced_model_has_no_cost(rec: TraceRecorder) -> None:
    await fake_model(_usage(10, 5)).ainvoke("hi", config={"callbacks": [rec.langchain_handler()]})

    assert store.latest_events(rec.run_id)[-1].cost_usd is None
