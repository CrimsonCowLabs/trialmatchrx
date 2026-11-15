"""compile_study: eligibility module -> cached, traced list[Criterion]. Fake model, no network."""

from typing import Any, get_args

import pytest
from pydantic import BaseModel
from sqlmodel import select

from app.db import CompiledCriteriaRow, session_scope
from app.pipeline import criteria_cache
from app.pipeline.compile_criteria import CompileFailed, DraftCriterion, compile_study
from app.pipeline.fixture_model import FixtureChatModel
from app.pipeline.predicate_fields import NUMERIC_OPS
from app.schemas import Criterion, Predicate, TraceEvent
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

TEXT = """Inclusion Criteria:

* Type 2 diabetes
* HbA1c \\>= 7%

Exclusion Criteria:

* Left ventricular ejection fraction \\<= 40%"""

DRAFT: dict[str, Any] = {
    "criteria": [
        {
            "type": "inclusion",
            "text": "Type 2 diabetes",
            "category": "diagnosis",
            "predicate": {"field": "conditions", "op": "has", "value": "type 2 diabetes"},
        },
        {
            "type": "inclusion",
            "text": "HbA1c >= 7%",
            "category": "lab",
            "predicate": {"field": "labs.hba1c", "op": ">=", "value": 7, "unit": "%"},
        },
        {
            "type": "exclusion",
            "text": "Left ventricular ejection fraction <= 40%",
            "category": "lab",
            # Not a PatientFacts lab: must be downgraded to needs_judgment.
            "predicate": {"field": "labs.lvef", "op": "<=", "value": 40, "unit": "%"},
        },
    ]
}


def study(text: str = TEXT, **elig: str) -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001"},
            "eligibilityModule": {"eligibilityCriteria": text, **elig},
        }
    }


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("compile", {}), EventBus())


def final_events(rec: TraceRecorder) -> list[TraceEvent]:
    return store.latest_events(rec.run_id)


def named(rec: TraceRecorder, name: str) -> TraceEvent:
    (event,) = [e for e in final_events(rec) if e.name == name]
    return event


async def test_llm_criteria_are_numbered_after_the_structured_ones() -> None:
    model = FixtureChatModel(output=DRAFT)

    criteria = await compile_study(
        study(minimumAge="18 Years", sex="ALL"), recorder(), model_factory=lambda: model
    )

    assert [c.id for c in criteria] == ["inc-age-min", "inc-1", "inc-2", "exc-1"]
    assert criteria[2] == Criterion(
        id="inc-2",
        type="inclusion",
        text="HbA1c >= 7%",
        category="lab",
        predicate=Predicate(field="labs.hba1c", op=">=", value=7, unit="%"),
        needs_judgment=False,
    )


async def test_invalid_predicate_path_is_downgraded_and_traced() -> None:
    rec = recorder()

    criteria = await compile_study(
        study(), rec, model_factory=lambda: FixtureChatModel(output=DRAFT)
    )

    exc = criteria[-1]
    assert (exc.id, exc.predicate, exc.needs_judgment) == ("exc-1", None, True)
    guard = named(rec, "predicate:exc-1")
    assert (guard.kind, guard.status) == ("guardrail", "failed")
    assert guard.output is not None and "unknown lab 'lvef'" in guard.output["error"]


async def test_age_and_sex_need_no_llm_call() -> None:
    model = FixtureChatModel(output=DRAFT)
    factory_calls = 0

    def factory() -> FixtureChatModel:
        nonlocal factory_calls
        factory_calls += 1
        return model

    criteria = await compile_study(
        study("", minimumAge="18 Years", maximumAge="75 Years", sex="FEMALE"),
        recorder(),
        model_factory=factory,
    )

    assert [c.id for c in criteria] == ["inc-age-min", "inc-age-max", "inc-sex"]
    assert all(c.predicate is not None for c in criteria)
    assert (factory_calls, model.calls) == (0, 0)


async def test_second_compile_is_a_cache_hit_and_force_bypasses_it() -> None:
    model = FixtureChatModel(output=DRAFT)

    first = recorder()
    compiled = await compile_study(study(), first, model_factory=lambda: model)
    assert named(first, "cache_lookup").cache_hit is False

    second = recorder()
    assert await compile_study(study(), second, model_factory=lambda: model) == compiled
    assert model.calls == 1
    assert named(second, "cache_lookup").cache_hit is True
    assert named(second, "compile_criteria").cache_hit is True
    assert not [e for e in final_events(second) if e.kind == "llm"]

    forced = recorder()
    await compile_study(study(), forced, model_factory=lambda: model, force=True)
    assert model.calls == 2
    lookup = named(forced, "cache_lookup")
    assert (lookup.status, lookup.cache_hit) == ("skipped", False)


async def test_llm_call_is_traced_with_prompt_output_tokens_and_cost() -> None:
    rec = recorder()

    await compile_study(study(), rec, model_factory=lambda: FixtureChatModel(output=DRAFT))

    (llm,) = [e for e in final_events(rec) if e.kind == "llm"]
    assert llm.status == "ok"
    assert llm.parent_id == named(rec, "llm_split").id
    assert llm.input is not None
    system, user = llm.input["messages"][0]
    assert system["role"] == "system" and "`labs.egfr`" in system["content"]
    assert "HbA1c >= 7%" in user["content"]  # markdown escapes removed before the LLM sees it
    assert llm.output is not None
    (call,) = llm.output["messages"][0]["tool_calls"]
    assert call["args"] == DRAFT
    assert llm.tokens_in and llm.tokens_out
    assert llm.cost_usd is not None and llm.cost_usd > 0

    top = named(rec, "compile_criteria")
    assert top.input is not None and top.input["prompt_version"] == "compile-criteria-v1"
    assert top.output is not None and top.output["compile_rate"] == pytest.approx(2 / 3)


async def test_a_quote_not_found_in_the_text_is_flagged() -> None:
    draft = {
        "criteria": [
            {
                "type": "inclusion",
                "text": "Diagnosed with type 2 diabetes",  # paraphrase, not in TEXT
                "category": "diagnosis",
                "predicate": None,
            }
        ]
    }
    rec = recorder()

    (crit,) = await compile_study(
        study(), rec, model_factory=lambda: FixtureChatModel(output=draft)
    )

    assert crit.needs_judgment
    guard = named(rec, "quote:inc-1")
    assert (guard.kind, guard.status) == ("guardrail", "failed")


async def test_malformed_llm_output_fails_the_step_with_compile_failed() -> None:
    rec = recorder()
    bad = {"criteria": [{"type": "maybe", "text": "T2D", "category": "lab", "predicate": None}]}

    with pytest.raises(CompileFailed, match="malformed compile output"):
        await compile_study(study(), rec, model_factory=lambda: FixtureChatModel(output=bad))

    assert named(rec, "llm_split").status == "failed"
    assert criteria_cache.latest("NCT00000001") == []


async def test_cache_records_the_model_that_ran_or_none() -> None:
    await compile_study(
        study(), recorder(), model_factory=lambda: FixtureChatModel(output=DRAFT, model_name="m-1")
    )
    other = {**study(""), "protocolSection": {**study("")["protocolSection"]}}
    other["protocolSection"]["identificationModule"] = {"nctId": "NCT00000002"}
    await compile_study(other, recorder(), model_factory=lambda: FixtureChatModel(output=DRAFT))

    with session_scope() as s:
        models = {r.nct_id: r.model for r in s.exec(select(CompiledCriteriaRow))}
    assert models == {"NCT00000001": "m-1", "NCT00000002": None}


def test_llm_category_and_ops_match_the_frozen_schema() -> None:
    def literal_values(model: type[BaseModel], name: str) -> set[object]:
        return set(get_args(model.model_fields[name].annotation))

    assert literal_values(DraftCriterion, "category") == literal_values(Criterion, "category")
    assert set(NUMERIC_OPS) <= literal_values(Predicate, "op")
