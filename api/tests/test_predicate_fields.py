"""A predicate may only name PatientFacts fields, with an op and value that fit the field."""

from typing import Any

import pytest

from app.pipeline.predicate_fields import (
    LAB_UNITS,
    InvalidPredicate,
    describe_vocabulary,
    validate_predicate,
)
from app.schemas import PatientFacts, Predicate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"field": "labs.egfr", "op": ">=", "value": 45, "unit": "mL/min/1.73 m²"},
            Predicate(field="labs.egfr", op=">=", value=45, unit="mL/min/1.73m2"),
        ),
        (
            {"field": "labs.hba1c", "op": "<", "value": 10, "unit": "%"},
            Predicate(field="labs.hba1c", op="<", value=10, unit="%"),
        ),
        (
            {"field": "vitals.bmi", "op": ">=", "value": 30},
            Predicate(field="vitals.bmi", op=">=", value=30, unit="kg/m2"),
        ),
        (
            {"field": "age", "op": ">=", "value": 40},
            Predicate(field="age", op=">=", value=40, unit="years"),
        ),
        (
            {"field": "conditions", "op": "has", "value": "Type 1 Diabetes"},
            Predicate(field="conditions", op="has", value="type 1 diabetes"),
        ),
        (
            {"field": "meds", "op": "in", "value": ["Spironolactone", "eplerenone"]},
            Predicate(field="meds", op="in", value=["spironolactone", "eplerenone"]),
        ),
        (
            {"field": "pregnant", "op": "==", "value": True},
            Predicate(field="pregnant", op="==", value="true"),
        ),
        (
            {"field": "sex", "op": "==", "value": "Female"},
            Predicate(field="sex", op="==", value="female"),
        ),
        (
            {"field": "labs.fvc_pct", "op": ">=", "value": 50, "unit": "%"},
            Predicate(field="labs.fvc_pct", op=">=", value=50, unit="% predicted"),
        ),
        (
            {"field": "labs.fev1_fvc", "op": "<", "value": 0.7},
            Predicate(field="labs.fev1_fvc", op="<", value=0.7, unit="ratio"),
        ),
        (
            {"field": "labs.alsfrs_r", "op": ">=", "value": 30, "unit": "points"},
            Predicate(field="labs.alsfrs_r", op=">=", value=30, unit="points"),
        ),
        (
            {"field": "labs.pvr", "op": ">=", "value": 3, "unit": "Wood units"},
            Predicate(field="labs.pvr", op=">=", value=3, unit="WU"),
        ),
        (
            {"field": "labs.six_mwd", "op": ">=", "value": 150, "unit": "m"},
            Predicate(field="labs.six_mwd", op=">=", value=150, unit="m"),
        ),
        (
            {"field": "labs.pcwp", "op": "<=", "value": 15, "unit": "mmHg"},
            Predicate(field="labs.pcwp", op="<=", value=15, unit="mmHg"),
        ),
    ],
)
def test_valid_predicates_are_normalized(raw: dict[str, Any], expected: Predicate) -> None:
    assert validate_predicate(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"field": "labs.ejection_fraction", "op": "<=", "value": 40}, "unknown lab"),
        ({"field": "history.mi", "op": "has", "value": "mi"}, "not a PatientFacts field"),
        ({"field": "egfr", "op": ">=", "value": 45}, "not a PatientFacts field"),
        ({"field": "lat", "op": ">=", "value": 38}, "not a PatientFacts field"),
        ({"field": "labs", "op": ">=", "value": 45}, "needs a key"),
        ({"field": "labs.egfr.value", "op": ">=", "value": 45}, "needs a key"),
        ({"field": "labs.egfr", "op": "between", "value": [25, 60]}, "op"),
        ({"field": "labs.egfr", "op": ">=", "value": "forty-five"}, "number"),
        ({"field": "labs.uacr", "op": ">=", "value": 3, "unit": "mg/mmol"}, "unit"),
        ({"field": "labs.pvr", "op": ">=", "value": 240, "unit": "dyn*s/cm5"}, "unit"),
        ({"field": "labs.fev1_fvc", "op": "<", "value": 70, "unit": "%"}, "unit"),
        ({"field": "conditions", "op": ">=", "value": 2}, "op"),
        ({"field": "conditions", "op": "has", "value": ""}, "non-empty"),
        ({"field": "smoker", "op": "==", "value": "sometimes"}, "true or false"),
        ({"field": "sex", "op": "==", "value": "other"}, "female or male"),
    ],
)
def test_invalid_predicates_are_rejected_with_a_reason(raw: dict[str, Any], reason: str) -> None:
    with pytest.raises(InvalidPredicate, match=reason):
        validate_predicate(raw)


def test_every_allowed_top_level_field_exists_on_patient_facts() -> None:
    from app.pipeline.predicate_fields import FIELD_KINDS

    assert set(FIELD_KINDS) <= set(PatientFacts.model_fields)


def test_the_compile_vocabulary_lists_the_pulmonary_and_als_measures() -> None:
    vocab = describe_vocabulary()
    for key in ("fvc_pct", "fev1_pct", "fev1_fvc", "svc_pct", "dlco_pct"):
        assert f"`labs.{key}` ({LAB_UNITS[key]})" in vocab
    for key in ("alsfrs_r", "six_mwd", "pvr", "pcwp"):
        assert f"`labs.{key}`" in vocab
    assert "`labs.fvc_pct` (% predicted)" in vocab and "`labs.pvr` (WU)" in vocab
