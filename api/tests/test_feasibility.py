"""Feasibility simulator (SPEC.md pipeline 6) on a six-patient fixture cohort.

    p1  T2D, eGFR 70           -> eligible on every rule
    p2  T2D, eGFR 50           -> fails eGFR >= 60, passes >= 45
    p3  T2D, eGFR 40           -> fails both thresholds
    p4  T2D, no eGFR           -> missing data on an inclusion: not counted eligible
    p5  hypertension, eGFR 80  -> no T2D
    p6  T2D, eGFR 65, kidney transplant -> excluded

Nobody's pregnancy is recorded, so the pregnancy exclusion keeps everyone (missing data on an
exclusion is no evidence of it).
"""

import pytest

from app.pipeline.evaluate import check_predicate
from app.pipeline.feasibility import MAX_CACHED_CHECKS, Cohort, InvalidOverride, simulate
from app.schemas import Criterion, Fact, PatientFacts, Predicate, WaterfallStep


def patient(conditions: list[str], egfr: float | None) -> PatientFacts:
    return PatientFacts(
        age=60,
        sex="female",
        conditions=[Fact(value=c) for c in conditions],
        labs={} if egfr is None else {"egfr": Fact(value=egfr, unit="mL/min/1.73m2")},
        vitals={},
        meds=[],
        pregnant=None,
        smoker=None,
        lat=None,
        lon=None,
    )


COHORT = Cohort.from_facts(
    [
        patient(["Type 2 diabetes mellitus"], 70),
        patient(["Type 2 diabetes mellitus"], 50),
        patient(["Type 2 diabetes mellitus"], 40),
        patient(["Type 2 diabetes mellitus"], None),
        patient(["Essential hypertension"], 80),
        patient(["Type 2 diabetes mellitus", "Kidney transplant"], 65),
    ]
)


def criterion(
    crit_id: str, field: str | None, op: str = "has", value: float | str = "", text: str = ""
) -> Criterion:
    predicate = (
        None
        if field is None
        else Predicate.model_validate({"field": field, "op": op, "value": value})
    )
    return Criterion(
        id=crit_id,
        type="inclusion" if crit_id.startswith("inc") else "exclusion",
        text=text or crit_id,
        category="other",
        predicate=predicate,
        needs_judgment=predicate is None,
    )


CRITERIA = [
    criterion("inc-1", "conditions", "has", "type 2 diabetes"),
    criterion("inc-2", "labs.egfr", ">=", 60),
    criterion("inc-3", None, text="Stable kidney function for 12 weeks"),
    criterion("exc-1", "conditions", "has", "kidney transplant"),
    criterion("exc-2", "pregnant", "==", "true"),
]


def steps(result_waterfall: list[WaterfallStep]) -> list[tuple[object, ...]]:
    return [(s.criterion_id, s.remaining, s.dropped, s.missing) for s in result_waterfall]


def test_waterfall_applies_rules_in_criterion_order() -> None:
    result = simulate("NCT1", CRITERIA, COHORT)

    assert result.cohort_size == 6
    assert steps(result.waterfall) == [
        ("inc-1", 5, 1, 0),
        ("inc-2", 2, 3, 1),
        ("exc-1", 1, 1, 0),
        ("exc-2", 1, 0, 1),
    ]


def test_overriding_a_threshold_reruns_the_waterfall() -> None:
    result = simulate("NCT1", CRITERIA, COHORT, overrides={"inc-2": 45})

    assert steps(result.waterfall)[1:3] == [("inc-2", 3, 2, 1), ("exc-1", 2, 1, 0)]
    egfr = result.waterfall[1]
    assert (egfr.value, egfr.default_value) == (45, 60)
    # Only thresholds get a slider: `pregnant == "true"` uses == but isn't a number.
    assert [s.numeric for s in result.waterfall] == [False, True, False, False]


def test_leave_one_out_counts_patients_each_rule_alone_removes() -> None:
    result = simulate("NCT1", CRITERIA, COHORT)

    assert [x.model_dump() for x in result.leave_one_out] == [
        {"criterion_id": "inc-1", "added_if_removed": 1},  # p5
        {"criterion_id": "inc-2", "added_if_removed": 3},  # p2, p3, p4
        {"criterion_id": "exc-1", "added_if_removed": 1},  # p6
        {"criterion_id": "exc-2", "added_if_removed": 0},
    ]


def test_leave_one_out_of_the_only_rule_adds_everyone_it_dropped() -> None:
    result = simulate("NCT1", [criterion("inc-2", "labs.egfr", ">=", 60)], COHORT)

    assert [x.model_dump() for x in result.leave_one_out] == [
        {"criterion_id": "inc-2", "added_if_removed": 3}
    ]


def test_criteria_without_a_predicate_are_needs_review_not_passed() -> None:
    result = simulate("NCT1", CRITERIA, COHORT, overrides={"inc-2": 45})

    assert "inc-3" not in [s.criterion_id for s in result.waterfall]
    assert [x.model_dump() for x in result.review_criteria] == [
        {
            "criterion_id": "inc-3",
            "text": "Stable kidney function for 12 weeks",
            "type": "inclusion",
            "access_barrier": None,
        }
    ]
    assert result.needs_review == 2  # p1 and p2 still have to be checked against inc-3


def test_needs_review_is_zero_when_every_criterion_has_a_predicate() -> None:
    rules_only = [c for c in CRITERIA if c.predicate is not None]

    result = simulate("NCT1", rules_only, COHORT)

    assert (result.needs_review, result.review_criteria) == (0, [])


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"inc-9": 45}, "no criterion 'inc-9'"),
        ({"inc-3": 45}, "inc-3 has no predicate"),
        ({"inc-2": "sixty"}, "inc-2: value must be a number"),
    ],
)
def test_bad_overrides_are_refused(overrides: dict[str, float | str], reason: str) -> None:
    with pytest.raises(InvalidOverride, match=reason):
        simulate("NCT1", CRITERIA, COHORT, overrides=overrides)


def test_a_name_the_record_does_not_list_is_absent() -> None:
    """Closed world for conditions / meds: `not_has` holds when the record doesn't list it."""
    no_transplant = criterion("inc-1", "conditions", "not_has", "kidney transplant")

    result = simulate("NCT1", [no_transplant], COHORT)

    assert steps(result.waterfall) == [("inc-1", 5, 1, 0)]


@pytest.mark.parametrize(
    "predicate",
    [
        {"field": "labs.egfr", "op": ">=", "value": 60},
        {"field": "labs.egfr", "op": "<", "value": 50},
        {"field": "labs.hba1c", "op": "<=", "value": 9},
        {"field": "age", "op": ">", "value": 59.5},
        {"field": "sex", "op": "==", "value": "female"},
        {"field": "pregnant", "op": "==", "value": "true"},
        {"field": "conditions", "op": "has", "value": "type 2 diabetes"},
        {"field": "conditions", "op": "in", "value": ["hypertension", "kidney transplant"]},
    ],
)
def test_cohort_checks_agree_with_the_matcher(predicate: dict[str, object]) -> None:
    """Wherever the matcher can answer a predicate for a patient, the cohort says the same.
    Where it can't, the cohort's answer is `missing`, except for conditions / meds (closed
    world: not listed means absent)."""
    patients = [
        patient(["Type 2 diabetes mellitus"], 70),
        patient(["Essential hypertension"], None),
        patient(["Kidney transplant"], 45.5),
    ]
    p = Predicate.model_validate(predicate)

    known, holds = Cohort.from_facts(patients).check(p)

    for i, facts in enumerate(patients):
        expected = check_predicate(p, facts).holds
        if expected is None and p.field in ("conditions", "meds"):
            expected = False
        assert (bool(known[i]), bool(holds[i])) == (expected is not None, bool(expected))


def test_slider_sweeps_keep_the_check_cache_bounded() -> None:
    cohort = Cohort.from_facts([patient([], 50)])
    egfr = criterion("inc-2", "labs.egfr", ">=", 60)

    for threshold in range(MAX_CACHED_CHECKS + 50):
        result = simulate("NCT1", [egfr], cohort, overrides={"inc-2": threshold})
        assert result.waterfall[0].remaining == (1 if threshold <= 50 else 0)

    assert len(cohort._checks) == MAX_CACHED_CHECKS


def test_demographic_rules_match_on_age_and_sex() -> None:
    rules = [criterion("inc-1", "age", ">=", 61), criterion("inc-2", "sex", "==", "male")]

    result = simulate("NCT1", rules, COHORT)

    assert steps(result.waterfall) == [("inc-1", 0, 6, 0), ("inc-2", 0, 0, 0)]
