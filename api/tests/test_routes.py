"""Every route in the SPEC API table answers with schema-valid data."""

from collections.abc import Iterator

import pytest

from app.config import get_settings
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
from tests.ctgov_fake import load
from tests.sse import client, parse_sse

MATCH_BODY = {"note": "61M, T2D, HbA1c 8.4%, eGFR 48, on metformin", "condition": "t2d"}


@pytest.fixture(autouse=True)
def no_stub_delay() -> Iterator[None]:
    settings = get_settings()
    original = settings.stub_event_delay_s
    settings.stub_event_delay_s = 0
    yield
    settings.stub_event_delay_s = original


async def test_stub_match_streams_five_trace_events_then_done() -> None:
    async with client() as c:
        started = await c.post("/api/match", json=MATCH_BODY)
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        messages = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)

    traces = [TraceEvent.model_validate(m.data) for m in messages if m.event == "trace"]
    assert len(traces) == 5
    assert [e.seq for e in traces] == [1, 2, 3, 4, 5]
    assert {e.run_id for e in traces} == {run_id}
    assert messages[-1].event == "done"


async def test_run_summary_and_trace_after_a_stub_match() -> None:
    async with client() as c:
        run_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        await c.get(f"/api/runs/{run_id}/events")  # returns once the run is done

        summary = RunSummary.model_validate((await c.get(f"/api/runs/{run_id}")).json())
        trace = [
            TraceEvent.model_validate(e) for e in (await c.get(f"/api/runs/{run_id}/trace")).json()
        ]

    assert summary.status == "done"
    assert summary.patient is not None and summary.patient.labs["egfr"].value == 48
    assert summary.totals.llm_calls == 1 and summary.totals.cache_hits == 1
    trace_ids = {e.id for e in trace}
    assert all(v.trace_event_id in trace_ids for m in summary.matches for v in m.verdicts)


async def test_match_needs_a_note_or_bundle() -> None:
    async with client() as c:
        response = await c.post("/api/match", json={"condition": "t2d"})
    assert response.status_code == 422


async def test_closer_starts_a_streamed_run() -> None:
    async with client() as c:
        match_id = (await c.post("/api/match", json=MATCH_BODY)).json()["run_id"]
        closer = await c.post("/api/closer", json={"run_id": match_id, "nct_id": "NCT00000000"})
        closer_id = closer.json()["run_id"]
        messages = parse_sse((await c.get(f"/api/runs/{closer_id}/events")).text)

    assert closer_id != match_id
    assert messages[-1].data == {"run_id": closer_id, "status": "done"}
    assert any(m.data.get("kind") == "tool" for m in messages if m.event == "trace")


async def test_trial_and_compile() -> None:
    study = load("study.json")
    ctgov.cache_study(study)
    nct, _ = ctgov.study_key(study)
    async with client() as c:
        trial = TrialDetail.model_validate((await c.get(f"/api/trials/{nct}")).json())
        compiled = await c.post(f"/api/trials/{nct}/compile", json={"force": True})
        run_id = compiled.headers["x-run-id"]
        trace = (await c.get(f"/api/runs/{run_id}/trace")).json()

    assert trial.nct_id == nct
    assert [Criterion.model_validate(c) for c in compiled.json()]
    assert [e["name"] for e in trace] == ["compile_criteria"]


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
