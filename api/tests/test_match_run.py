"""End-to-end match: POST /api/match -> background run -> GET /api/runs/{id}. No network: the
trials come from saved fixtures in the ctgov cache, their criteria from the compile cache."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.main import app
from app.pipeline import judge as judge_module
from app.pipeline.compile_criteria import compile_study
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.study_source import load_fixture_study
from app.routers.match import judge_model_factory
from app.schemas import RunSummary, TraceEvent, Verdict
from app.sources import ctgov
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.sse import client, parse_sse

# Fixture trials with a site near Sacramento: ~0 mi, ~132 mi, ~368 mi.
NEAR = ["NCT07662135", "NCT07271186", "NCT07783802"]
FHIR_FIXTURES = Path(__file__).parent / "fixtures" / "fhir"
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
    # Warm compile cache: the only LLM call is the (fixture) note parse.
    assert summary.totals.llm_calls == 1
    names = [e.name for e in trace if e.parent_id is None]
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


async def test_a_request_without_a_radius_searches_100_miles(no_api_key: None) -> None:
    # The seeded reach (config.ctgov_seed_radius_mi), not SPEC.md's 50 mi: far trials show a
    # distance warning in the UI instead of being dropped.
    assert get_settings().ctgov_seed_radius_mi == 100
    await cache_and_compile(NEAR)
    body = {k: v for k, v in BODY.items() if k != "radius_mi"}
    _, trace, _ = await run(body)
    search = next(e for e in trace if e.name == "search_trials")
    assert search.input is not None and search.input["radius_mi"] == 100
    # ~0 mi in, ~132 mi out.
    assert search.output is not None and search.output["nct_ids"] == ["NCT07662135"]
    assert search.note is not None and "within 100 mi" in search.note


async def test_a_fhir_bundle_is_mapped_without_an_llm(
    no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    await cache_and_compile(["NCT07271186"])
    bundle = json.loads((FHIR_FIXTURES / "full.json").read_text())
    summary, trace, _ = await run({**BODY, "note": None, "fhir_bundle": bundle})

    assert summary.status == "done"
    patient = summary.patient
    assert patient is not None and patient.sex == "female"
    assert patient.labs["hba1c"].value == 8.6 and patient.labs["egfr"].value == 44
    assert patient.vitals["sbp"].value == 142
    # The mapping is one traced step with no llm event under it; the note parser never ran.
    (step,) = [e for e in trace if e.name == "parse_patient"]
    assert step.kind == "step" and step.status == "ok"
    assert step.input is not None and step.input["source"] == "fhir_bundle"
    assert not any(e.parent_id == step.id for e in trace)
    assert fixture_parse_model.calls == 0
    assert summary.totals.llm_calls == 0
    # The mapped facts drive the rules: T2D, HbA1c 8.6 and eGFR 44 pass on NCT07271186.
    [m] = summary.matches
    by_text: dict[str, list[str]] = {}
    for v in m.verdicts:
        by_text.setdefault(v.criterion_quote, []).append(v.outcome)
    assert by_text["Medical history of type 2 diabetes"] == ["pass"]
    assert by_text["Hemoglobin A1C (HbA1c) of 6.5 to 10% at screening"] == ["pass", "pass"]


# NCT07271186's first criterion with no predicate, and patient evidence from BODY's note.
REAL_QUOTE = "receiving medical therapy or lifestyle interventions for glucose management"
JUDGED = {"inc-2", "exc-1", "exc-2", "exc-4"}  # NCT07271186 criteria without a predicate


def install_judge(output: dict[str, Any]) -> FixtureChatModel:
    model = FixtureChatModel(output=output, tool_name="JudgeOutput", model_name="claude-judge")
    app.dependency_overrides[judge_model_factory] = lambda: lambda: model
    return model


def judged(summary: RunSummary) -> list[Verdict]:
    return [v for m in summary.matches for v in m.verdicts if v.method == "llm"]


async def test_criteria_without_a_rule_go_to_the_judge(no_api_key: None) -> None:
    await cache_and_compile(["NCT07271186"])
    model = install_judge(
        {
            "outcome": "pass",
            "criterion_quote": REAL_QUOTE,
            "patient_evidence": "on metformin",
            "rationale": "On metformin, so receiving medical therapy for glucose.",
        }
    )
    summary, trace, _ = await run(BODY)

    verdicts = judged(summary)
    assert {v.criterion_id for v in verdicts} == JUDGED
    assert model.calls == len(JUDGED)
    assert all(v.outcome == "pass" and v.verified for v in verdicts)
    events = {e.id: e for e in trace}
    for v in verdicts:
        step = events[v.trace_event_id]
        assert step.name == f"judge:NCT07271186:{v.criterion_id}"
        assert any(e.kind == "llm" and e.parent_id == step.id for e in trace)
    assert summary.totals.llm_calls == 1 + len(JUDGED)  # the note parse + one per judged criterion
    assert not [e for e in trace if e.name.startswith("verify:") and e.status == "failed"]


async def test_a_fabricated_judge_quote_is_downgraded_in_the_run(no_api_key: None) -> None:
    await cache_and_compile(["NCT07271186"])
    install_judge(
        {
            "outcome": "fail",
            "criterion_quote": "History of pancreatitis within 6 months",  # not in this trial
            "patient_evidence": "on metformin",
            "rationale": "Made up.",
        }
    )
    summary, trace, _ = await run(BODY)

    verdicts = judged(summary)
    assert {v.criterion_id for v in verdicts} == JUDGED
    assert all(v.outcome == "unknown" and not v.verified for v in verdicts)
    tripped = [e for e in trace if e.name.startswith("verify:") and e.status == "failed"]
    assert len(tripped) == len(JUDGED)
    assert summary.totals.guardrail_trips >= len(JUDGED)  # plus any from the note parse
    assert summary.matches[0].tier != "ineligible"  # the fabricated fails never landed


async def test_no_judge_model_leaves_unruled_criteria_unknown(no_api_key: None) -> None:
    await cache_and_compile(["NCT07271186"])
    summary, trace, _ = await run(BODY)

    assert summary.status == "done"
    assert judged(summary) == []
    by_id = {v.criterion_id: v for v in summary.matches[0].verdicts}
    assert all(by_id[c].outcome == "unknown" for c in JUDGED)
    skipped = next(e for e in trace if e.name == "judge")
    assert skipped.status == "skipped" and skipped.output is not None
    assert "JudgeModelUnavailable" in skipped.output["error"]


async def test_one_judge_semaphore_bounds_calls_across_all_trials(
    no_api_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await cache_and_compile(NEAR)
    install_judge(
        {
            "outcome": "unknown",
            "criterion_quote": "x",
            "patient_evidence": None,
            "rationale": "unused",
        }
    )
    in_flight = peak = calls = 0
    real = judge_module.judge_criterion

    async def slow(*args: Any, **kwargs: Any) -> Verdict:
        nonlocal in_flight, peak, calls
        in_flight += 1
        calls += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        try:
            return await real(*args, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(judge_module, "judge_criterion", slow)
    summary, _, _ = await run(BODY)

    assert summary.status == "done"
    assert calls > judge_module.JUDGE_CONCURRENCY  # enough work across trials to hit the bound
    assert peak == judge_module.JUDGE_CONCURRENCY
