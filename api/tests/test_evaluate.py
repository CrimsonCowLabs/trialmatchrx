"""evaluate: Criterion x PatientFacts -> Verdict, each one backed by a `rule` trace event."""

from typing import Any

from app.pipeline.evaluate import evaluate_criterion, evaluate_trial
from app.schemas import Criterion, Fact, PatientFacts, Predicate, Verdict
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

NCT = "NCT00000001"


def patient(**overrides: Any) -> PatientFacts:
    base: dict[str, Any] = {
        "age": 61,
        "sex": "male",
        "conditions": [Fact(value="type 2 diabetes mellitus", source_span="type 2 diabetes")],
        "labs": {"egfr": Fact(value=48, unit="mL/min/1.73m2", source_span="eGFR 48")},
        "vitals": {},
        "meds": [Fact(value="metformin", source_span="on metformin")],
        "pregnant": False,
        "smoker": None,
        "lat": None,
        "lon": None,
    }
    return PatientFacts(**{**base, **overrides})


def criterion(
    field: str,
    op: str,
    value: Any,
    *,
    type: str = "inclusion",
    unit: str | None = None,
    crit_id: str = "inc-1",
) -> Criterion:
    return Criterion(
        id=crit_id,
        type=type,  # type: ignore[arg-type]
        text=f"{field} {op} {value}",
        category="other",
        predicate=Predicate.model_validate(
            {"field": field, "op": op, "value": value, "unit": unit}
        ),
        needs_judgment=False,
    )


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


async def outcome(crit: Criterion, facts: PatientFacts | None = None) -> str:
    verdict = await evaluate_criterion(NCT, crit, facts or patient(), recorder())
    return verdict.outcome


async def test_missing_lab_is_unknown_not_fail() -> None:
    crit = criterion("labs.hba1c", ">=", 7, unit="%")
    assert await outcome(crit) == "unknown"
    exclusion = criterion("labs.hba1c", ">", 10, unit="%", type="exclusion")
    assert await outcome(exclusion) == "unknown"


async def test_verdict_points_at_its_rule_event() -> None:
    rec = recorder()
    crit = criterion("labs.egfr", ">=", 45, unit="mL/min/1.73m2")
    verdict: Verdict = await evaluate_criterion(NCT, crit, patient(), rec)

    events = {e.id: e for e in store.latest_events(rec.run_id)}
    event = events[verdict.trace_event_id]
    assert event.kind == "rule"
    assert event.name == f"rule:{NCT}:inc-1"
    assert event.output is not None and event.output["outcome"] == "pass"
    assert verdict.method == "rule"
    assert verdict.criterion_quote == crit.text
    assert verdict.patient_evidence == "eGFR 48"


async def test_exclusion_is_inverted() -> None:
    # eGFR 48: "eGFR < 30" as an exclusion doesn't apply (pass); "eGFR < 60" disqualifies.
    assert await outcome(criterion("labs.egfr", "<", 30, type="exclusion")) == "pass"
    assert await outcome(criterion("labs.egfr", "<", 60, type="exclusion")) == "fail"
    assert await outcome(criterion("labs.egfr", ">=", 60)) == "fail"


async def test_age_vitals_sex_and_flags() -> None:
    bmi = {"bmi": Fact(value=31.2, unit="kg/m2")}
    assert await outcome(criterion("age", ">=", 18, unit="years")) == "pass"
    assert await outcome(criterion("age", "<=", 60, unit="years")) == "fail"
    assert await outcome(criterion("age", ">=", 18), patient(age=None)) == "unknown"
    assert await outcome(criterion("vitals.bmi", "<=", 30), patient(vitals=bmi)) == "fail"
    assert await outcome(criterion("vitals.sbp", "<", 160)) == "unknown"
    assert await outcome(criterion("sex", "==", "male")) == "pass"
    assert await outcome(criterion("sex", "==", "female")) == "fail"
    assert await outcome(criterion("sex", "==", "female"), patient(sex=None)) == "unknown"
    assert await outcome(criterion("pregnant", "==", "true", type="exclusion")) == "pass"
    smoking = criterion("smoker", "==", "true", type="exclusion")
    assert await outcome(smoking) == "unknown"
    assert await outcome(smoking, patient(smoker=True)) == "fail"


async def test_listed_condition_or_med_is_evidence_either_way() -> None:
    assert await outcome(criterion("conditions", "has", "type 2 diabetes")) == "pass"
    t2d_excluded = criterion("conditions", "has", "type 2 diabetes", type="exclusion")
    assert await outcome(t2d_excluded) == "fail"
    insulin_or_metformin = ["insulin glargine", "metformin"]
    on_either = criterion("meds", "in", insulin_or_metformin, type="exclusion")
    assert await outcome(on_either) == "fail"
    assert await outcome(criterion("meds", "not_has", "metformin")) == "fail"


async def test_absent_condition_can_clear_but_never_disqualify() -> None:
    # Not in the list: an exclusion doesn't apply, but an unmet inclusion is only unknown.
    assert await outcome(criterion("conditions", "has", "type 1 diabetes", type="exclusion")) == (
        "pass"
    )
    assert await outcome(criterion("conditions", "has", "chronic kidney disease")) == "unknown"
    assert await outcome(criterion("meds", "not_has", "insulin")) == "pass"
    assert await outcome(criterion("meds", "not_has", "insulin", type="exclusion")) == "unknown"


async def test_empty_list_is_unknown() -> None:
    nothing = patient(conditions=[], meds=[])
    exclusion = criterion("conditions", "has", "heart failure", type="exclusion")
    assert await outcome(exclusion, nothing) == "unknown"
    assert await outcome(criterion("meds", "has", "metformin"), nothing) == "unknown"


JUDGMENT = Criterion(
    id="exc-2",
    type="exclusion",
    text="History of diabetic ketoacidosis within the past 6 months",
    category="history",
    predicate=None,
    needs_judgment=True,
)


async def test_criterion_without_predicate_is_unknown_with_a_traced_event() -> None:
    rec = recorder()
    verdict = await evaluate_criterion(NCT, JUDGMENT, patient(), rec)

    event = {e.id: e for e in store.latest_events(rec.run_id)}[verdict.trace_event_id]
    assert verdict.outcome == "unknown"
    assert verdict.criterion_quote == JUDGMENT.text
    assert event.kind == "rule" and event.status == "skipped"
    assert event.name == f"rule:{NCT}:exc-2"


async def test_trial_verdicts_keep_order_and_send_only_unruled_criteria_to_the_judge() -> None:
    judged: list[str] = []

    async def judge(
        nct_id: str, crit: Criterion, facts: PatientFacts, rec: TraceRecorder
    ) -> Verdict:
        judged.append(crit.id)
        event = rec.event(f"judge:{nct_id}:{crit.id}", "llm")
        return Verdict(
            criterion_id=crit.id,
            outcome="pass",
            method="llm",
            criterion_quote=crit.text,
            patient_evidence=None,
            rationale="fake judge",
            verified=True,
            trace_event_id=event.id,
        )

    rule = criterion("labs.egfr", ">=", 45)
    verdicts = await evaluate_trial(NCT, [JUDGMENT, rule], patient(), recorder(), judge=judge)

    assert [v.criterion_id for v in verdicts] == ["exc-2", "inc-1"]
    assert [v.method for v in verdicts] == ["llm", "rule"]
    assert judged == ["exc-2"]


async def test_lab_in_another_unit_is_unknown() -> None:
    other_unit = {"egfr": Fact(value=0.8, unit="mL/s/1.73m2")}
    crit = criterion("labs.egfr", ">=", 45, unit="mL/min/1.73m2")
    assert await outcome(crit, patient(labs=other_unit)) == "unknown"
