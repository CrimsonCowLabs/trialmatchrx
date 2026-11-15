"""POST /api/feasibility/{nct}: compiled criteria from the cache x the cohort table."""

import random
import statistics
import time

import pytest

from app.pipeline import criteria_cache
from app.schemas import Criterion, Fact, FeasibilityResult, PatientFacts, Predicate
from app.sources.cohort import get_cohort, replace_cohort, reset_cohort
from tests.sse import client

NCT = "NCT07271186"
CONDITIONS = [
    "Type 2 diabetes mellitus",
    "Chronic kidney disease stage 3",
    "Essential hypertension",
    "Hyperlipidemia",
    "Kidney transplant",
    "Type 1 diabetes mellitus",
]
MEDS = ["24 HR Metformin hydrochloride 500 MG", "Lisinopril 10 MG", "Insulin isophane", "None"]


def synthetic_patient(rng: random.Random) -> PatientFacts:
    """A random patient in the shape the Synthea mapper produces (canonical units)."""
    labs = {
        "egfr": Fact(value=round(rng.uniform(10, 120), 1), unit="mL/min/1.73m2"),
        "hba1c": Fact(value=round(rng.uniform(5, 12), 1), unit="%"),
        "uacr": Fact(value=round(rng.uniform(5, 3000)), unit="mg/g"),
    }
    vitals = {
        "bmi": Fact(value=round(rng.uniform(18, 45), 1), unit="kg/m2"),
        "sbp": Fact(value=rng.randint(95, 180), unit="mmHg"),
        "dbp": Fact(value=rng.randint(55, 110), unit="mmHg"),
    }
    return PatientFacts(
        age=rng.randint(40, 85),
        sex=rng.choice(["female", "male"]),
        conditions=[Fact(value=c) for c in CONDITIONS if rng.random() < 0.3],
        labs={k: v for k, v in labs.items() if rng.random() < 0.7},  # some labs never drawn
        vitals=vitals,
        meds=[Fact(value=m) for m in MEDS if rng.random() < 0.3],
        pregnant=None,
        smoker=rng.choice([True, False, None]),
        lat=None,
        lon=None,
    )


def rule(crit_id: str, text: str, field: str, op: str, value: float | str | list[str]) -> Criterion:
    return Criterion(
        id=crit_id,
        type="inclusion" if crit_id.startswith("inc") else "exclusion",
        text=text,
        category="lab" if field.startswith("labs") else "other",
        predicate=Predicate.model_validate({"field": field, "op": op, "value": value}),
        needs_judgment=False,
    )


def review(crit_id: str, text: str) -> Criterion:
    kind = "inclusion" if crit_id.startswith("inc") else "exclusion"
    return Criterion(
        id=crit_id, type=kind, text=text, category="other", predicate=None, needs_judgment=True
    )


# Shaped like a compiled T2D/CKD trial: 14 rules and 4 criteria that need review.
CRITERIA = [
    rule("inc-age-min", "Minimum age: 18 Years", "age", ">=", 18),
    rule("inc-age-max", "Maximum age: 80 Years", "age", "<=", 80),
    rule("inc-1", "Medical history of type 2 diabetes", "conditions", "has", "type 2 diabetes"),
    review("inc-2", "receiving medical therapy or lifestyle interventions for glucose"),
    rule("inc-3", "HbA1c of 6.5 to 10%", "labs.hba1c", ">=", 6.5),
    rule("inc-4", "HbA1c of 6.5 to 10%", "labs.hba1c", "<=", 10),
    rule("inc-5", "eGFR >= 60 mL/min/1.73 m^2", "labs.egfr", ">=", 60),
    rule("inc-6", "eGFR <= 90 mL/min/1.73 m^2", "labs.egfr", "<=", 90),
    rule("inc-7", "UACR of 30 to 5000 mg/g", "labs.uacr", ">=", 30),
    rule("inc-8", "BMI >= 23", "vitals.bmi", ">=", 23),
    review("exc-1", "non-diabetic kidney disease"),
    rule("exc-2", "Type 1 diabetes", "conditions", "has", "type 1 diabetes"),
    rule("exc-3", "kidney transplant", "conditions", "in", ["kidney transplant", "dialysis"]),
    rule("exc-4", "Pregnancy", "pregnant", "==", "true"),
    rule("exc-5", "Uncontrolled hypertension (SBP >= 160)", "vitals.sbp", ">=", 160),
    rule("exc-6", "Current smoker", "smoker", "==", "true"),
    review("exc-7", "Medically unstable as assessed by the investigator"),
    review("exc-8", "Participation in another trial"),
]


def load(n: int, seed: int = 9) -> None:
    rng = random.Random(seed)
    replace_cohort((f"p{i:04d}", "synthetic", synthetic_patient(rng)) for i in range(n))


@pytest.fixture(autouse=True)
def fresh_cohort() -> None:
    reset_cohort()  # the DataFrame is process-wide; each test has its own database


async def test_no_cohort_is_503() -> None:
    criteria_cache.put(NCT, "h", "v1", None, CRITERIA)
    async with client() as c:
        response = await c.post(f"/api/feasibility/{NCT}", json={"overrides": {}})
    assert response.status_code == 503
    assert "make seed" in response.json()["detail"]


async def test_uncompiled_trial_is_404() -> None:
    load(10)
    async with client() as c:
        response = await c.post("/api/feasibility/NCT0", json={"overrides": {}})
    assert response.status_code == 404


async def test_bad_override_is_422() -> None:
    load(10)
    criteria_cache.put(NCT, "h", "v1", None, CRITERIA)
    async with client() as c:
        response = await c.post(f"/api/feasibility/{NCT}", json={"overrides": {"exc-1": 3}})
    assert response.status_code == 422
    assert "exc-1 has no predicate" in response.json()["detail"]


async def test_lowering_the_egfr_threshold_grows_the_eligible_pool() -> None:
    load(1000)
    criteria_cache.put(NCT, "h", "v1", None, CRITERIA)
    async with client() as c:
        strict = FeasibilityResult.model_validate(
            (await c.post(f"/api/feasibility/{NCT}", json={"overrides": {}})).json()
        )
        loose = FeasibilityResult.model_validate(
            (await c.post(f"/api/feasibility/{NCT}", json={"overrides": {"inc-5": 45}})).json()
        )

    assert strict.cohort_size == loose.cohort_size == 1000
    assert loose.waterfall[-1].remaining > strict.waterfall[-1].remaining > 0
    egfr = {s.criterion_id: s for s in loose.waterfall}["inc-5"]
    assert (egfr.value, egfr.default_value, egfr.numeric) == (45, 60, True)
    assert [r.criterion_id for r in loose.review_criteria] == [
        "inc-2",
        "exc-1",
        "exc-7",
        "exc-8",
    ]
    assert loose.needs_review == loose.waterfall[-1].remaining


async def test_responds_under_100_ms_over_a_1000_patient_cohort() -> None:
    """SPEC.md: no LLM and under 100 ms, so the slider can call it on every change. Timed end to
    end through the ASGI app (criteria read from SQLite, every rule over the DataFrame,
    leave-one-out, JSON), first request included. The cohort itself is read at startup."""
    load(1000)
    criteria_cache.put(NCT, "h", "v1", None, CRITERIA)
    assert get_cohort().size == 1000  # what the app's lifespan does at startup

    timings_ms = []
    async with client() as c:
        for threshold in [60, 59, 55, 50, 45, 40, 45, 50, 60, 30, 75, 60]:
            started = time.perf_counter()
            body = {"overrides": {"inc-5": threshold, "inc-3": 7.0}}
            response = await c.post(f"/api/feasibility/{NCT}", json=body)
            timings_ms.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200

    print(
        f"feasibility over 1000 patients: first {timings_ms[0]:.1f} ms, "
        f"median {statistics.median(timings_ms):.1f} ms, max {max(timings_ms):.1f} ms"
    )
    assert max(timings_ms) < 100


async def test_waterfall_and_review_rows_carry_access_barriers_of_cached_criteria() -> None:
    """Criteria cached before the flag existed are flagged on the way out (issue #53)."""
    load(10)
    weekly = "Willing to attend weekly study visits, BMI >= 23"
    criteria_cache.put(
        NCT,
        "h",
        "v1",
        None,
        [
            rule("inc-1", weekly, "vitals.bmi", ">=", 23),
            rule("inc-2", "eGFR >= 60 mL/min/1.73 m^2", "labs.egfr", ">=", 60),
            review("inc-3", "Able to read and write English"),
            review("exc-1", "Participation in another trial"),
        ],
    )

    async with client() as c:
        response = await c.post(f"/api/feasibility/{NCT}", json={"overrides": {}})

    result = FeasibilityResult.model_validate(response.json())
    assert [(w.criterion_id, w.access_barrier) for w in result.waterfall] == [
        ("inc-1", "visit_burden"),
        ("inc-2", None),
    ]
    assert [(r.criterion_id, r.access_barrier) for r in result.review_criteria] == [
        ("inc-3", "language"),
        ("exc-1", None),
    ]
