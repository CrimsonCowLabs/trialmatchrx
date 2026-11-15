"""Synthea FHIR bundle -> PatientFacts (SPEC.md pipeline 1, FHIR path). Deterministic, no LLM.

Fixtures in tests/fixtures/fhir are hand-written synthetic Synthea-style bundles.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas import Fact
from app.sources import synthea
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

FHIR = Path(__file__).parent / "fixtures" / "fhir"
AS_OF = dt.date(2026, 11, 12)


def bundle(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FHIR / f"{name}.json").read_text())
    return data


def test_demographics_and_location() -> None:
    facts = synthea.facts_from_bundle(bundle("full"), as_of=AS_OF)
    assert facts.age == 62  # born 1964-03-15
    assert facts.sex == "female"
    assert (facts.lat, facts.lon) == (38.5816, -121.4944)


def test_most_recent_lab_wins_with_its_unit_and_date() -> None:
    labs = synthea.facts_from_bundle(bundle("full"), as_of=AS_OF).labs
    assert labs["hba1c"] == Fact(value=8.6, unit="%", date=dt.date(2026, 9, 20))
    # eGFR is reported under 33914-3 (2025, 52) and 62238-1 (2026, 44): newest across both.
    assert labs["egfr"] == Fact(value=44.0, unit="mL/min/1.73m2", date=dt.date(2026, 9, 20))
    assert set(labs) == {"hba1c", "egfr"}


def test_most_recent_vitals_including_the_blood_pressure_panel() -> None:
    vitals = synthea.facts_from_bundle(bundle("full"), as_of=AS_OF).vitals
    sep_20 = dt.date(2026, 9, 20)
    assert vitals == {
        "bmi": Fact(value=32.4, unit="kg/m2", date=sep_20),
        "sbp": Fact(value=142, unit="mmHg", date=sep_20),
        "dbp": Fact(value=88, unit="mmHg", date=sep_20),
    }


def test_missing_observations_leave_fields_empty() -> None:
    facts = synthea.facts_from_bundle(bundle("sparse"), as_of=AS_OF)
    assert facts.age == 68 and facts.sex == "male"
    assert facts.labs == {} and facts.vitals == {}
    assert facts.meds == []
    assert facts.smoker is None and facts.pregnant is None
    assert facts.lat is None and facts.lon is None


def test_active_conditions_only_without_the_snomed_semantic_tag() -> None:
    conditions = synthea.facts_from_bundle(bundle("full"), as_of=AS_OF).conditions
    assert conditions == [
        # SNOMED 44054006 gets the name compiled predicates use ("has type 2 diabetes").
        Fact(value="type 2 diabetes mellitus", date=dt.date(2015, 6, 1)),
        Fact(value="Chronic kidney disease stage 3", date=dt.date(2022, 2, 10)),
        Fact(value="Essential hypertension", date=dt.date(2012, 4, 22)),
    ]  # the resolved acute bronchitis is left out


def test_a_refuted_or_mistaken_condition_is_left_out() -> None:
    data = bundle("full")
    for entry in data["entry"]:
        if entry["resource"]["id"] == "c-htn":
            entry["resource"]["verificationStatus"] = {"coding": [{"code": "entered-in-error"}]}
    names = [c.value for c in synthea.facts_from_bundle(data, as_of=AS_OF).conditions]
    assert names == ["type 2 diabetes mellitus", "Chronic kidney disease stage 3"]


def test_active_medication_requests_only() -> None:
    meds = synthea.facts_from_bundle(bundle("full"), as_of=AS_OF).meds
    assert meds == [
        Fact(
            value="24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet",
            date=dt.date(2016, 7, 1),
        ),
        Fact(value="lisinopril 10 MG Oral Tablet", date=dt.date(2022, 3, 15)),
    ]  # the stopped amoxicillin is left out


def test_most_recent_smoking_status_wins() -> None:
    # 2010 "Smoker", 2026 "Ex-smoker": a former smoker is not a smoker now.
    assert synthea.facts_from_bundle(bundle("full"), as_of=AS_OF).smoker is False


def test_a_reading_in_a_non_canonical_unit_is_dropped_not_converted() -> None:
    data = bundle("full")
    for entry in data["entry"]:
        if entry["resource"]["id"] == "o-a1c-3":  # the newest HbA1c, 8.6 %
            entry["resource"]["valueQuantity"].update(value=70, unit="mmol/mol", code="mmol/mol")
    mapping = synthea.map_bundle(data, as_of=AS_OF)
    # The newest usable reading wins instead: 2025-05-01, 8.1 %.
    assert mapping.facts.labs["hba1c"] == Fact(value=8.1, unit="%", date=dt.date(2025, 5, 1))
    assert mapping.dropped == ["labs.hba1c (o-a1c-3): unit 'mmol/mol' is not '%'"]


@pytest.mark.parametrize(
    "data",
    [
        {"resourceType": "Patient", "id": "x"},
        {"resourceType": "Bundle", "entry": []},
        {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Patient"}}] * 2},
    ],
    ids=["not-a-bundle", "no-patient", "two-patients"],
)
def test_a_bundle_needs_exactly_one_patient(data: dict[str, Any]) -> None:
    with pytest.raises(synthea.InvalidBundle):
        synthea.check_bundle(data)
    with pytest.raises(synthea.InvalidBundle):
        synthea.facts_from_bundle(data, as_of=AS_OF)


async def test_mapping_is_one_traced_step_with_no_llm_event() -> None:
    rec = TraceRecorder(store.create_run("match", {}), EventBus())
    facts = await synthea.parse_bundle(rec, bundle("sparse"), as_of=AS_OF)

    assert facts == synthea.facts_from_bundle(bundle("sparse"), as_of=AS_OF)
    events = store.latest_events(rec.run_id)
    (step,) = events
    assert step.kind == "step" and step.name == "parse_patient" and step.status == "ok"
    assert step.input == {
        "source": "fhir_bundle",
        "resources": {"Patient": 1, "Condition": 1, "Observation": 1},
    }
    assert step.output is not None
    assert step.output["patient"] == facts.model_dump(mode="json")
    assert step.output["missing"] == [
        "labs.hba1c",
        "labs.egfr",
        "vitals.bmi",
        "vitals.sbp",
        "vitals.dbp",
        "smoker",
        "lat/lon",
    ]
