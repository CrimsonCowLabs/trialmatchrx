"""End-to-end match: POST /api/match -> background run -> GET /api/runs/{id}. No network: the
trials come from saved fixtures in the ctgov cache, their criteria from the compile cache."""

from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.main import app
from app.pipeline.compile_criteria import compile_study
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.study_source import load_fixture_study
from app.routers.trials import compile_model_factory
from app.schemas import RunSummary, TraceEvent
from app.sources import ctgov
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.sse import client, parse_sse

# Fixture trials with a site near Sacramento: ~0 mi, ~132 mi, ~368 mi.
NEAR = ["NCT07662135", "NCT07271186", "NCT07783802"]
BODY = {
    "note": "61M, T2D, HbA1c 8.4%, eGFR 48, on metformin",
    "condition": "type 2 diabetes",
    "radius_mi": 400,
}


async def cache_and_compile(ncts: list[str]) -> None:
    rec = TraceRecorder(store.create_run("compile", {}), EventBus())
    for nct in ncts:
        study = load_fixture_study(nct)
        ctgov.cache_study(study)
        model = FixtureChatModel(output=load_llm_fixture(nct))
        await compile_study(study, rec, model_factory=lambda m=model: m)


@pytest.fixture
def no_api_key() -> Iterator[None]:
    """A compile-cache miss must not reach Anthropic: the real factory raises without a key."""
    app.dependency_overrides.pop(compile_model_factory, None)
    settings = get_settings()
    original, settings.anthropic_api_key = settings.anthropic_api_key, None
    yield
    settings.anthropic_api_key = original


async def run(body: dict[str, object]) -> tuple[RunSummary, list[TraceEvent], list[str]]:
    async with client() as c:
        run_id = (await c.post("/api/match", json=body)).json()["run_id"]
        streamed = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        summary = RunSummary.model_validate((await c.get(f"/api/runs/{run_id}")).json())
        trace = [
            TraceEvent.model_validate(e) for e in (await c.get(f"/api/runs/{run_id}/trace")).json()
        ]
    return summary, trace, [m.event for m in streamed]


async def test_demo_patient_gets_ranked_tiered_matches(no_api_key: None) -> None:
    await cache_and_compile(NEAR)
    summary, trace, streamed = await run(BODY)

    assert streamed[-1] == "done"
    assert summary.status == "done"
    assert summary.patient is not None and summary.patient.labs["egfr"].value == 48
    assert sorted(m.nct_id for m in summary.matches) == sorted(NEAR)
    order = {"likely": 0, "needs_info": 1, "ineligible": 2}
    keys = [(order[m.tier], m.counts["unknown"]) for m in summary.matches]
    assert keys == sorted(keys)
    for m in summary.matches:
        assert sum(m.counts.values()) == len(m.verdicts) > 0
    # Warm compile cache: no LLM calls; one cache hit per trial.
    assert summary.totals.llm_calls == 0
    names = [e.name for e in trace]
    assert names[:2] == ["parse_patient", "search_trials"]
    assert names[-1] == "rank"


async def test_every_verdict_points_at_the_rule_event_that_produced_it(no_api_key: None) -> None:
    await cache_and_compile(NEAR)
    summary, trace, _ = await run(BODY)

    events = {e.id: e for e in trace}
    trial_steps = {e.name: e.id for e in trace if e.name.startswith("trial:")}
    for m in summary.matches:
        for v in m.verdicts:
            event = events[v.trace_event_id]
            assert event.kind == "rule"
            assert event.name == f"rule:{m.nct_id}:{v.criterion_id}"
            assert event.output is not None and event.output["outcome"] == v.outcome
            assert event.parent_id == trial_steps[f"trial:{m.nct_id}"]


async def test_demo_patient_verdicts_on_a_known_trial(no_api_key: None) -> None:
    # NCT07271186 inclusions: T2D (has), HbA1c 6.5-10 (8.4), eGFR 30-90 (48), UACR 500-5000
    # (not in the demo facts -> unknown, never fail).
    await cache_and_compile(["NCT07271186"])
    summary, _, _ = await run(BODY)

    [m] = summary.matches
    by_text = {}
    for v in m.verdicts:
        by_text.setdefault(v.criterion_quote, []).append(v.outcome)
    assert by_text["Medical history of type 2 diabetes"] == ["pass"]
    assert by_text["Hemoglobin A1C (HbA1c) of 6.5 to 10% at screening"] == ["pass", "pass"]
    uacr = next(q for q in by_text if q.startswith("Albuminuria"))
    assert by_text[uacr] == ["unknown", "unknown"]


async def test_trial_that_cannot_be_compiled_is_skipped_not_fatal(no_api_key: None) -> None:
    await cache_and_compile(["NCT07662135"])
    ctgov.cache_study(load_fixture_study("NCT07271186"))  # cached, never compiled, no key
    summary, trace, _ = await run(BODY)

    assert summary.status == "done"
    assert [m.nct_id for m in summary.matches] == ["NCT07662135"]
    skipped = next(e for e in trace if e.name == "trial:NCT07271186")
    assert skipped.status == "failed"
    assert skipped.output is not None and "CompileModelUnavailable" in skipped.output["error"]


async def test_radius_limits_the_trials(no_api_key: None) -> None:
    await cache_and_compile(NEAR)
    summary, _, _ = await run({**BODY, "radius_mi": 50})
    assert [m.nct_id for m in summary.matches] == ["NCT07662135"]
    assert summary.matches[0].distance_mi is not None and summary.matches[0].distance_mi < 1
