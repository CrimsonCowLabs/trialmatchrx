"""Every route in the SPEC API table answers with schema-valid data."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import get_settings
from app.main import app
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.study_source import load_fixture_study
from app.routers.trials import compile_model_factory
from app.schemas import (
    Criterion,
    EvalLatest,
    FeasibilityResult,
    Health,
    RunSummary,
    TraceEvent,
    TrialDetail,
)
from app.sources import ctgov
from tests.ctgov_fake import FakeCtgov
from tests.sse import client, parse_sse

PARSE_FIXTURES = Path(__file__).parent / "fixtures" / "parse_patient"
FHIR_FIXTURES = Path(__file__).parent / "fixtures" / "fhir"
DEMO_NOTE = (PARSE_FIXTURES / "demo_short.txt").read_text()
MATCH_BODY = {"note": DEMO_NOTE, "condition": "t2d"}


@pytest.fixture(autouse=True)
def no_stub_delay() -> Iterator[None]:
    settings = get_settings()
    original = settings.stub_event_delay_s
    settings.stub_event_delay_s = 0
    yield
    settings.stub_event_delay_s = original


async def test_match_streams_trace_events_in_seq_order_then_done() -> None:
    async with client() as c:
        started = await c.post("/api/match", json=MATCH_BODY)
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        messages = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)

    traces = [TraceEvent.model_validate(m.data) for m in messages if m.event == "trace"]
    assert [e.seq for e in traces] == list(range(1, len(traces) + 1))
    assert {e.run_id for e in traces} == {run_id}
    assert messages[-1].event == "done"


async def test_match_parses_the_note_into_the_run_result_and_trace(
    fixture_parse_model: FixtureChatModel,
) -> None:
    async with client() as c:
        run_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        await c.get(f"/api/runs/{run_id}/events")
        summary = RunSummary.model_validate((await c.get(f"/api/runs/{run_id}")).json())
        trace = [
            TraceEvent.model_validate(e) for e in (await c.get(f"/api/runs/{run_id}/trace")).json()
        ]

    assert fixture_parse_model.calls == 1
    patient = summary.patient
    assert patient is not None and patient.age == 61 and patient.sex == "male"
    assert patient.labs["hba1c"].value == 8.4 and patient.labs["hba1c"].source_span in DEMO_NOTE
    (step,) = [e for e in trace if e.name == "parse_patient"]
    assert step.status == "ok" and step.kind == "step"
    assert any(e.kind == "llm" and e.parent_id == step.id for e in trace)


async def test_trace_export_is_the_streamed_events_in_their_final_state() -> None:
    """`GET /trace` (Export JSON / replay) holds exactly what the SSE stream showed: one entry
    per event, in its final state, in order of first appearance."""
    async with client() as c:
        run_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        messages = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        trace = [
            TraceEvent.model_validate(e) for e in (await c.get(f"/api/runs/{run_id}/trace")).json()
        ]

    streamed: dict[str, TraceEvent] = {}
    for m in messages:
        if m.event == "trace":
            event = TraceEvent.model_validate(m.data)
            streamed[event.id] = event
    assert trace == list(streamed.values())
    assert len({e.id for e in trace}) == len(trace)
    assert all(e.status != "started" and e.ended_at is not None for e in trace)
    # every seq of the run is either some event's final emission or a step's `started` one
    assert max(e.seq for e in trace) == sum(m.event == "trace" for m in messages)


async def test_match_needs_a_note_or_bundle() -> None:
    async with client() as c:
        response = await c.post("/api/match", json={"condition": "t2d"})
    assert response.status_code == 422


async def test_match_takes_a_note_or_a_bundle_not_both() -> None:
    bundle = json.loads((FHIR_FIXTURES / "sparse.json").read_text())
    async with client() as c:
        response = await c.post("/api/match", json={**MATCH_BODY, "fhir_bundle": bundle})
    assert response.status_code == 422
    assert "exactly one" in response.json()["detail"]


async def test_match_rejects_a_bundle_without_one_patient() -> None:
    body = {"fhir_bundle": {"resourceType": "Bundle", "entry": []}, "condition": "t2d"}
    async with client() as c:
        response = await c.post("/api/match", json=body)
    assert response.status_code == 422
    assert "Patient" in response.json()["detail"]


async def test_closer_starts_a_streamed_run() -> None:
    async with client() as c:
        match_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        closer = await c.post("/api/closer", json={"run_id": match_id, "nct_id": "NCT00000000"})
        closer_id = closer.json()["run_id"]
        messages = parse_sse((await c.get(f"/api/runs/{closer_id}/events")).text)

    assert closer_id != match_id
    assert messages[-1].data == {"run_id": closer_id, "status": "done"}
    assert any(m.data.get("kind") == "tool" for m in messages if m.event == "trace")


FIXTURE_NCT = "NCT07271186"


@pytest.fixture
def fixture_compile_model() -> Iterator[FixtureChatModel]:
    model = FixtureChatModel(output=load_llm_fixture(FIXTURE_NCT))
    app.dependency_overrides[compile_model_factory] = lambda: lambda: model
    yield model
    app.dependency_overrides.pop(compile_model_factory)


async def test_trial_and_compile(fixture_compile_model: FixtureChatModel) -> None:
    ctgov.cache_study(load_fixture_study(FIXTURE_NCT))
    async with client() as c:
        before = TrialDetail.model_validate((await c.get(f"/api/trials/{FIXTURE_NCT}")).json())
        compiled = await c.post(f"/api/trials/{FIXTURE_NCT}/compile", json={"force": False})
        again = await c.post(f"/api/trials/{FIXTURE_NCT}/compile", json={})
        after = TrialDetail.model_validate((await c.get(f"/api/trials/{FIXTURE_NCT}")).json())
        trace = (await c.get(f"/api/runs/{again.headers['x-run-id']}/trace")).json()

    assert before.nct_id == FIXTURE_NCT
    assert before.criteria == []  # not compiled yet
    assert compiled.status_code == 200
    criteria = [Criterion.model_validate(c) for c in compiled.json()]
    assert criteria[:2] == [c for c in criteria if c.id.startswith("inc-age")]
    assert after.criteria == criteria
    assert again.json() == compiled.json()
    assert fixture_compile_model.calls == 1
    assert any(e["name"] == "ctgov.cache_lookup" and e["cache_hit"] for e in trace)
    lookup = next(e for e in trace if e["name"] == "cache_lookup")
    assert lookup["cache_hit"] is True


async def test_compile_unknown_trial_is_404() -> None:
    FakeCtgov().install()  # answers 404 for any study it doesn't hold
    async with client() as c:
        response = await c.post("/api/trials/NCT99999999/compile", json={"force": True})
    assert response.status_code == 404


async def test_compile_without_api_key_on_a_cache_miss_is_503() -> None:
    settings = get_settings()
    original, settings.anthropic_api_key = settings.anthropic_api_key, None
    ctgov.cache_study(load_fixture_study(FIXTURE_NCT))
    try:
        async with client() as c:
            response = await c.post(f"/api/trials/{FIXTURE_NCT}/compile", json={"force": True})
    finally:
        settings.anthropic_api_key = original
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


async def test_feasibility_eval_health() -> None:
    async with client() as c:
        loose = FeasibilityResult.model_validate(
            (await c.post("/api/feasibility/NCT1", json={"overrides": {"inc-1": 45}})).json()
        )
        strict = FeasibilityResult.model_validate(
            (await c.post("/api/feasibility/NCT1", json={"overrides": {"inc-1": 60}})).json()
        )
        EvalLatest.model_validate((await c.get("/api/eval/latest")).json())
        health = Health.model_validate((await c.get("/api/health")).json())

    assert loose.waterfall[-1]["remaining"] > strict.waterfall[-1]["remaining"]
    assert health.ok and health.demo_mode == "off"


async def test_unknown_run_routes_404() -> None:
    async with client() as c:
        for path in ("/api/runs/nope", "/api/runs/nope/trace"):
            assert (await c.get(path)).status_code == 404
        response = await c.post("/api/closer", json={"run_id": "nope", "nct_id": "NCT1"})
        assert response.status_code == 404
