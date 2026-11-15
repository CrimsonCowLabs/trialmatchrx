"""parse_patient: note -> PatientFacts with verified source spans. Fake model, no network."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.pipeline.fixture_model import FixtureChatModel
from app.pipeline.parse_patient import ParseFailed, ParseModelUnavailable, parse_patient
from app.schemas import PatientFacts, TraceEvent
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

FIXTURES = Path(__file__).parent / "fixtures" / "parse_patient"


def note(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


def draft(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def model(output: dict[str, Any]) -> FixtureChatModel:
    return FixtureChatModel(output=output, model_name=get_settings().model_parse)


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


def events(rec: TraceRecorder) -> list[TraceEvent]:
    return store.latest_events(rec.run_id)


async def parse(
    name: str, output: dict[str, Any] | None = None
) -> tuple[PatientFacts, TraceRecorder]:
    rec = recorder()
    fake = model(output if output is not None else draft(name))
    facts = await parse_patient(rec, note(name), model_factory=lambda: fake)
    return facts, rec


async def test_demo_patient_parses_into_correct_facts() -> None:
    facts, _ = await parse("demo_short")

    assert facts.age == 61
    assert facts.sex == "male"
    assert [c.value for c in facts.conditions] == ["type 2 diabetes"]
    assert facts.labs["hba1c"].value == 8.4 and facts.labs["hba1c"].unit == "%"
    assert facts.labs["egfr"].value == 48 and facts.labs["egfr"].unit == "mL/min/1.73m2"
    assert [m.value for m in facts.meds] == ["metformin"]
    assert facts.lat is not None and facts.lon is not None
    assert abs(facts.lat - 38.58) < 0.1 and abs(facts.lon + 121.49) < 0.1


async def test_the_place_is_kept_as_written_once_its_span_is_verified() -> None:
    facts, _ = await parse("demo_short")
    assert facts.place == "Sacramento, CA"


async def test_a_location_whose_span_is_not_in_the_note_leaves_no_place() -> None:
    output = draft("demo_short")
    output["location"]["source_span"] = "Fresno"
    facts, _ = await parse("demo_short", output)
    assert facts.place is None and facts.lat is None


def all_spans(facts: PatientFacts) -> list[str | None]:
    listed = [*facts.conditions, *facts.meds, *facts.labs.values(), *facts.vitals.values()]
    return [f.source_span for f in listed]


@pytest.mark.parametrize("name", ["demo_short", "demo_note"])
async def test_every_fact_carries_a_span_that_appears_in_the_note(name: str) -> None:
    facts, rec = await parse(name)

    spans = all_spans(facts)
    assert spans and all(s is not None and s in note(name) for s in spans)
    (step,) = [e for e in events(rec) if e.name == "parse_patient"]
    assert step.output is not None and step.output["dropped"] == []
    assert all(s in note(name) for s in step.output["scalar_spans"].values())
    assert not [e for e in events(rec) if e.kind == "guardrail"]


async def test_the_full_demo_note_parses_labs_vitals_and_dates() -> None:
    facts, _ = await parse("demo_note")

    assert facts.labs["egfr"].date == dt.date(2026, 10, 2)
    assert facts.labs["uacr"].value == 120
    assert (facts.vitals["sbp"].value, facts.vitals["dbp"].value) == (138, 84)
    assert [m.value for m in facts.meds] == ["metformin", "lisinopril"]
    assert facts.smoker is False
    assert facts.pregnant is None  # not stated, so not inferred


async def test_a_fact_whose_span_is_not_in_the_note_is_dropped_with_a_guardrail() -> None:
    output = draft("demo_short")
    output["meds"].append({"value": "insulin glargine", "source_span": "on insulin glargine"})
    output["age"] = {"value": 62, "source_span": "62-year-old"}

    facts, rec = await parse("demo_short", output)

    assert [m.value for m in facts.meds] == ["metformin"]
    assert facts.age is None
    guards = [e for e in events(rec) if e.kind == "guardrail"]
    assert sorted(e.name for e in guards) == ["span:age", "span:meds[1]"]
    assert all(e.status == "failed" for e in guards)
    # The web Patient facts panel lists these as unverified: it reads the parse step's
    # guardrail children and their `input.path` / `input.fact`.
    step = next(e for e in events(rec) if e.name == "parse_patient")
    meds = next(e for e in guards if e.name == "span:meds[1]")
    assert meds.parent_id == step.id
    assert meds.input is not None
    assert meds.input["path"] == "meds[1]"
    assert meds.input["fact"]["source_span"] == "on insulin glargine"


@pytest.mark.parametrize("unit", ["mmol/mol", None])
async def test_a_lab_in_a_missing_or_non_canonical_unit_is_dropped(unit: str | None) -> None:
    output = draft("demo_short")
    output["labs"][0] = {"name": "hba1c", "value": 68, "unit": unit, "source_span": "HbA1c"}

    facts, rec = await parse("demo_short", output)

    assert "hba1c" not in facts.labs
    assert [e.name for e in events(rec) if e.kind == "guardrail"] == ["unit:labs.hba1c"]


async def test_a_span_must_match_whole_words() -> None:
    output = draft("demo_short")
    output["sex"] = {"value": "female", "source_span": "F"}  # only inside "metformin"
    output["conditions"].append({"value": "type 2 diabetes", "source_span": "T2"})

    facts, rec = await parse("demo_short", output)

    assert facts.sex is None
    assert len(facts.conditions) == 1
    guards = sorted(e.name for e in events(rec) if e.kind == "guardrail")
    assert guards == ["span:conditions[1]", "span:sex"]


async def test_spans_match_case_and_whitespace_insensitively_and_keep_the_note_text() -> None:
    output = draft("demo_short")
    output["labs"][1]["source_span"] = "EGFR  48"

    facts, _ = await parse("demo_short", output)

    assert facts.labs["egfr"].source_span == "eGFR 48"


async def test_the_parse_llm_call_is_in_the_trace_under_the_parse_step() -> None:
    _, rec = await parse("demo_short")

    trace = events(rec)
    (step,) = [e for e in trace if e.name == "parse_patient"]
    (llm,) = [e for e in trace if e.kind == "llm"]
    assert llm.parent_id == step.id
    assert llm.model == get_settings().model_parse
    assert llm.tokens_in and llm.tokens_out and llm.cost_usd is not None
    assert llm.input is not None and "HbA1c 8.4%" in json.dumps(llm.input)
    assert llm.output is not None
    (answer,) = llm.output["messages"]
    assert json.loads(answer["content"]) == draft("demo_short") and "tool_calls" not in answer
    assert step.input is not None and step.input["prompt_version"] == "parse-patient-v3"
    assert step.output is not None and step.output["patient"]["labs"]["egfr"]["value"] == 48


@pytest.mark.parametrize("empty", [None, "null"])
async def test_a_null_or_null_string_list_is_read_as_empty(empty: str | None) -> None:
    output = draft("demo_short")
    output["meds"] = empty  # Haiku has answered `"meds": "null"` for a note with no meds

    facts, _ = await parse("demo_short", output)

    assert facts.meds == []
    assert facts.labs["egfr"].value == 48


async def test_malformed_model_output_fails_the_parse_step() -> None:
    rec = recorder()
    fake = model({"age": {"value": "sixty-one"}})

    with pytest.raises(ParseFailed):
        await parse_patient(rec, note("demo_short"), model_factory=lambda: fake)
    (step,) = [e for e in events(rec) if e.name == "parse_patient"]
    assert step.status == "failed"


async def test_without_an_api_key_the_real_model_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    with pytest.raises(ParseModelUnavailable):
        await parse_patient(recorder(), note("demo_short"))
