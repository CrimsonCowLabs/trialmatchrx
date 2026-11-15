"""Closer agent (SPEC.md pipeline 5): its four tools on a fixture match run, the CloserOutput
contract, the recursion limit, and what streams into the trace. No network: the match run is
built from saved fixtures, the agent's model is scripted."""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from app.main import app
from app.pipeline.closer_agent import RECURSION_LIMIT, CloserToolError, closer_tools
from app.routers.match import closer_model_factory
from app.schemas import CloserOutput, RunSummary, TraceEvent
from tests.scripted_model import ScriptedChatModel, reply
from tests.sse import SSEMessage, client, parse_sse
from tests.test_match_run import BODY, cache_and_compile

TRIAL = "NCT07271186"  # Regeneron; UACR inclusions are unknown for the demo patient
FIXTURES = Path(__file__).parent / "fixtures" / "closer"


async def fixture_match_run() -> str:
    """A finished match run for the demo note against TRIAL (saved fixtures, no network)."""
    await cache_and_compile([TRIAL])
    async with client() as c:
        run_id: str = (await c.post("/api/match", json=BODY)).json()["run_id"]
        parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)  # wait for `done`
    return run_id


def tool(name: str) -> BaseTool:
    return next(t for t in closer_tools() if t.name == name)


async def call(name: str, **args: Any) -> Any:
    """Invoke a tool by name with keyword args; returns its (JSON-able) result."""
    return await tool(name).ainvoke(args)


@pytest.fixture
async def run_id(no_api_key: None) -> str:
    return await fixture_match_run()


# --- tools -----------------------------------------------------------------------------------


async def test_get_patient_facts_returns_the_parsed_patient_and_note(run_id: str) -> None:
    out = await call("get_patient_facts", run_id=run_id)
    assert out["patient"]["age"] == 61
    assert out["patient"]["labs"]["egfr"]["value"] == 48
    assert out["note"] == BODY["note"]


async def test_get_match_result_returns_the_trial_as_ranked(run_id: str) -> None:
    out = await call("get_match_result", run_id=run_id, nct=TRIAL)
    assert out["nct_id"] == TRIAL
    assert out["tier"] == "needs_info"
    assert out["counts"] == {"pass": 7, "fail": 0, "unknown": 7}
    assert len(out["verdicts"]) == 14
    assert out["title"].startswith("Study to Assess the Effects of ALN-ANG3")


async def test_get_unknown_criteria_lists_each_unknown_with_its_trial_text(run_id: str) -> None:
    out = await call("get_unknown_criteria", run_id=run_id, nct=TRIAL)
    by_id = {c["criterion_id"]: c for c in out["criteria"]}
    assert list(by_id) == ["inc-2", "inc-7", "inc-8", "exc-1", "exc-2", "exc-3", "exc-4"]
    uacr = by_id["inc-7"]
    assert uacr["type"] == "inclusion"
    assert uacr["category"] == "lab"
    assert uacr["text"].startswith("Albuminuria: Urine Albumin to Creatinine Ratio (UACR)")
    assert uacr["rationale"]  # why it is unknown, from the matcher
    assert by_id["exc-3"]["type"] == "exclusion"


async def test_get_trial_contacts_gives_central_contacts_and_nearest_sites() -> None:
    await cache_and_compile([TRIAL])
    out = await call("get_trial_contacts", nct=TRIAL)
    assert out["central_contacts"] == [
        {
            "name": "Clinical Trials Administrator",
            "role": "CONTACT",
            "phone": "844-734-6643",
            "email": "clinicaltrials@regeneron.com",
        }
    ]
    sites = out["nearest_sites"]
    assert 1 <= len(sites) <= 3
    assert sites[0]["distance_mi"] == pytest.approx(131.8, abs=0.1)  # as the match run ranked it
    assert [s["distance_mi"] for s in sites] == sorted(s["distance_mi"] for s in sites)


async def test_tools_refuse_what_the_run_does_not_hold(run_id: str) -> None:
    with pytest.raises(CloserToolError, match="NCT07662135"):
        await call("get_match_result", run_id=run_id, nct="NCT07662135")
    with pytest.raises(CloserToolError, match="nope"):
        await call("get_patient_facts", run_id="nope")
    with pytest.raises(CloserToolError, match="NCT07662135"):
        await call("get_trial_contacts", nct="NCT07662135")  # not cached: no network fallback


# --- CloserOutput ----------------------------------------------------------------------------

DEMO_OUTPUT = json.loads((FIXTURES / "demo_output.json").read_text())


def test_closer_output_holds_followups_an_email_and_a_bilingual_summary() -> None:
    out = CloserOutput.model_validate(DEMO_OUTPUT)
    assert out.followups[0].criterion_id == "inc-2"
    assert {f.kind for f in out.followups} <= {"test", "question"}
    assert out.coordinator_email.subject and out.coordinator_email.body
    assert out.patient_summary.en and out.patient_summary.es


@pytest.mark.parametrize(
    "broken",
    [
        {"patient_summary": {"en": "Only English."}},  # Spanish is required
        {"followups": [{"criterion_id": "inc-7", "kind": "referral", "action": "x", "why": "y"}]},
        {"coordinator_email": "a bare string"},
    ],
)
def test_closer_output_rejects_incomplete_answers(broken: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CloserOutput.model_validate({**DEMO_OUTPUT, **broken})


# --- the agent run (POST /api/closer) --------------------------------------------------------

TOOL_NAMES = ["get_match_result", "get_unknown_criteria", "get_trial_contacts", "get_patient_facts"]


def happy_script(run_id: str, output: dict[str, Any] = DEMO_OUTPUT) -> list[AIMessage]:
    """Sonnet's expected shape: all four tools in one turn, a closing thought, the answer."""
    return [
        reply(
            "I'll pull the match, the unknown criteria, the contacts and the patient.",
            *happy_calls(run_id),
        ),
        reply("Seven criteria are unknown; one UACR test and five questions resolve them."),
        reply("", ("CloserOutput", output)),
    ]


@pytest.fixture
def install_model() -> Iterator[Callable[[ScriptedChatModel], None]]:
    def install(model: ScriptedChatModel) -> None:
        app.dependency_overrides[closer_model_factory] = lambda: lambda: model

    yield install
    app.dependency_overrides.pop(closer_model_factory, None)


async def run_closer(
    match_run_id: str, nct: str = TRIAL
) -> tuple[RunSummary, list[SSEMessage], list[TraceEvent]]:
    async with client() as c:
        started = await c.post("/api/closer", json={"run_id": match_run_id, "nct_id": nct})
        assert started.status_code == 200, started.text
        closer_id = started.json()["run_id"]
        streamed = parse_sse((await c.get(f"/api/runs/{closer_id}/events")).text)
        summary = RunSummary.model_validate((await c.get(f"/api/runs/{closer_id}")).json())
        trace = [
            TraceEvent.model_validate(e)
            for e in (await c.get(f"/api/runs/{closer_id}/trace")).json()
        ]
    return summary, streamed, trace


def emissions(streamed: list[SSEMessage], name: str) -> list[tuple[int, str]]:
    """(seq, status) of every streamed emission of the events called `name`."""
    return [
        (int(m.id or 0), m.data["status"])
        for m in streamed
        if m.event == "trace" and m.data["name"] == name
    ]


async def test_the_agent_writes_next_steps_and_streams_every_step(
    run_id: str, install_model: Callable[[ScriptedChatModel], None]
) -> None:
    install_model(model := ScriptedChatModel(replies=happy_script(run_id)))
    summary, streamed, trace = await run_closer(run_id)

    assert summary.kind == "closer" and summary.status == "done"
    assert summary.closer == CloserOutput.model_validate(DEMO_OUTPUT)
    assert model.calls == 3  # tools turn, closing thought, structured answer
    assert streamed[-1].event == "done"

    agent = next(e for e in trace if e.name == "closer_agent")
    tools = [e for e in trace if e.kind == "tool"]
    assert sorted(e.name for e in tools) == sorted(TOOL_NAMES)
    for event in tools:
        assert event.parent_id == agent.id and event.status == "ok"
        assert event.output and event.output["result"]  # the tool result is in the trace
        # Streamed as it happened: `started` first, then the result.
        assert [s for _, s in emissions(streamed, event.name)] == ["started", "ok"]

    thoughts = [e for e in trace if e.name == "thought"]
    assert [t.note for t in thoughts] == [
        "I'll pull the match, the unknown criteria, the contacts and the patient.",
        "Seven criteria are unknown; one UACR test and five questions resolve them.",
    ]
    assert thoughts[0].output == {
        "text": thoughts[0].note,
        "tool_calls": [{"name": n, "args": a} for n, a in happy_calls(run_id)],
    }
    # Order on the wire: thought -> tool calls -> tool results -> next thought.
    first_thought, second_thought = (emissions(streamed, "thought")[i][0] for i in (0, 1))
    tool_seqs = [seq for name in TOOL_NAMES for seq, _ in emissions(streamed, name)]
    assert first_thought < min(tool_seqs) < max(tool_seqs) < second_thought

    assert sum(e.kind == "llm" for e in trace) == 3
    coverage = next(e for e in trace if e.name == "closer:followup_coverage")
    assert coverage.kind == "guardrail" and coverage.status == "ok"


def happy_calls(run_id: str) -> list[tuple[str, dict[str, Any]]]:
    by_run = {"run_id": run_id, "nct": TRIAL}
    return [
        ("get_match_result", by_run),
        ("get_unknown_criteria", by_run),
        ("get_trial_contacts", {"nct": TRIAL}),
        ("get_patient_facts", {"run_id": run_id}),
    ]


async def test_hitting_the_recursion_limit_is_an_error_event(
    run_id: str, install_model: Callable[[ScriptedChatModel], None]
) -> None:
    looping = ScriptedChatModel(replies=[reply("Let me check once more.", *happy_calls(run_id))])
    install_model(looping)
    summary, streamed, trace = await run_closer(run_id)

    assert summary.status == "failed" and summary.closer is None
    assert streamed[-1].data["status"] == "failed"
    error = next(e for e in trace if e.name == "closer_agent:recursion_limit")
    assert error.kind == "error" and error.status == "failed"
    assert error.output is not None and error.output["recursion_limit"] == RECURSION_LIMIT
    # The agent stopped inside the limit (one model call per agent step, tool steps between)
    # and never asked for a structured answer it couldn't have.
    assert looping.calls <= RECURSION_LIMIT // 2
    assert sum(e.kind == "llm" for e in trace) == looping.calls


async def test_followups_missing_an_unknown_criterion_trip_a_guardrail(
    run_id: str, install_model: Callable[[ScriptedChatModel], None]
) -> None:
    partial = {**DEMO_OUTPUT, "followups": DEMO_OUTPUT["followups"][:-1]}  # drops exc-4
    install_model(ScriptedChatModel(replies=happy_script(run_id, partial)))
    summary, _, trace = await run_closer(run_id)

    assert summary.status == "done"
    coverage = next(e for e in trace if e.name == "closer:followup_coverage")
    assert coverage.status == "failed"
    assert coverage.output is not None and coverage.output["missing"] == ["exc-4"]
    assert summary.totals.guardrail_trips == 1


async def test_a_failing_tool_call_is_traced_and_the_agent_carries_on(
    run_id: str, install_model: Callable[[ScriptedChatModel], None]
) -> None:
    wrong = reply("Checking a trial.", ("get_match_result", {"run_id": run_id, "nct": "NCT1"}))
    install_model(ScriptedChatModel(replies=[wrong, *happy_script(run_id)]))
    summary, _, trace = await run_closer(run_id)

    assert summary.status == "done"
    failed = [e for e in trace if e.kind == "tool" and e.status == "failed"]
    assert [e.name for e in failed] == ["get_match_result"]
    assert failed[0].output is not None and "NCT1" in failed[0].output["error"]


async def test_closer_route_rejects_bad_requests(
    run_id: str, install_model: Callable[[ScriptedChatModel], None]
) -> None:
    install_model(ScriptedChatModel(replies=[reply("unused")]))
    async with client() as c:
        no_run = await c.post("/api/closer", json={"run_id": "nope", "nct_id": TRIAL})
        no_trial = await c.post("/api/closer", json={"run_id": run_id, "nct_id": "NCT07662135"})
    assert no_run.status_code == 404
    assert no_trial.status_code == 404 and "NCT07662135" in no_trial.text


async def test_closer_route_without_an_api_key_is_503(run_id: str) -> None:
    async with client() as c:
        response = await c.post("/api/closer", json={"run_id": run_id, "nct_id": TRIAL})
    assert response.status_code == 503
