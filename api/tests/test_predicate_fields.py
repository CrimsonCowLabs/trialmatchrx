"""A predicate may only name PatientFacts fields, with an op and value that fit the field."""

from typing import Any

import pytest

from app.pipeline.predicate_fields import InvalidPredicate, validate_predicate
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
