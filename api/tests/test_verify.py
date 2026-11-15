"""Quote verification guardrail: are the judge's quotes really in their sources?"""

import datetime as dt
from typing import Any

from app.pipeline.verify import quote_present, verify_verdict
from app.schemas import Fact, PatientFacts, TraceEvent, Verdict
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

NOTE = """61-year-old man with type 2 diabetes  diagnosed 2014.
Labs 2026-10-02: HbA1c 8.4%, eGFR 48 mL/min/1.73m2.
Meds: metformin 1000 mg twice daily."""


def test_exact_quote_is_present() -> None:
    assert quote_present("HbA1c 8.4%", [NOTE])


def test_matching_ignores_case_and_whitespace() -> None:
    assert quote_present("TYPE 2 DIABETES\n diagnosed 2014", [NOTE])


def test_small_typos_are_tolerated() -> None:
    assert quote_present("metformin 1000mg twice daily", [NOTE])


def test_fabricated_quote_is_not_present() -> None:
    assert not quote_present("history of acute pancreatitis", [NOTE])


def test_a_changed_number_is_not_present() -> None:
    # Fuzzy ratio alone scores these >= 85; clinical numbers must match exactly.
    assert not quote_present("eGFR 148", [NOTE])
    assert not quote_present("eGFR 45 mL/min/1.73m2", [NOTE])


def test_an_added_or_dropped_negation_is_not_present() -> None:
    source = "PMH: history of pancreatitis in 2019. Denies tobacco use."
    # Fuzzy ratio alone scores the first at ~92: an invented "no" would flip an exclusion.
    assert not quote_present("no history of pancreatitis", [source])
    assert not quote_present("tobacco use", [source])  # drops the "denies" just before it
    assert quote_present("Denies tobacco use", [source])
    assert quote_present("history of pancreatitis", [source])


def test_quote_longer_than_its_source_is_not_present() -> None:
    # partial_ratio would score the short source inside the long quote at 100.
    assert not quote_present("on metformin 1000 mg twice daily plus insulin", ["metformin"])


def test_blank_quote_or_no_source_is_not_present() -> None:
    assert not quote_present("  ", [NOTE])
    assert not quote_present("HbA1c 8.4%", [])
    assert not quote_present("HbA1c 8.4%", [""])


def test_any_source_may_contain_the_quote() -> None:
    assert quote_present("labs.egfr: 48 mL/min/1.73m2", ["no labs", "labs.egfr: 48 mL/min/1.73m2"])


# --------------------------------------------------------------------------------------------
# verify_verdict: downgrade + guardrail event
# --------------------------------------------------------------------------------------------

TRIAL_TEXT = """Inclusion Criteria:

* Type 2 diabetes treated with metformin for at least 3 months
* eGFR 25 to 75 mL/min/1.73m2

Exclusion Criteria:

* History of acute or chronic pancreatitis"""

FACTS = PatientFacts(
    age=61,
    sex="male",
    conditions=[Fact(value="type 2 diabetes", source_span="type 2 diabetes  diagnosed 2014")],
    labs={"egfr": Fact(value=48, unit="mL/min/1.73m2", date=dt.date(2026, 10, 2))},
    vitals={},
    meds=[Fact(value="metformin")],
    pregnant=None,
    smoker=None,
    lat=None,
    lon=None,
)


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("match", {}), EventBus())


def verdict(**overrides: Any) -> Verdict:
    base: dict[str, Any] = {
        "criterion_id": "inc-1",
        "outcome": "pass",
        "method": "llm",
        "criterion_quote": "Type 2 diabetes treated with metformin for at least 3 months",
        "patient_evidence": "Meds: metformin 1000 mg twice daily.",
        "rationale": "On metformin since at least 2014.",
        "verified": False,
        "trace_event_id": "judge-step",
    }
    return Verdict.model_validate(base | overrides)


def check(rec: TraceRecorder, v: Verdict, note: str | None = NOTE) -> Verdict:
    out: Verdict = verify_verdict(
        rec, v, label="NCT00000001:inc-1", trial_text=TRIAL_TEXT, note=note, facts=FACTS
    )
    return out


def guardrails(rec: TraceRecorder) -> list[TraceEvent]:
    return [e for e in store.latest_events(rec.run_id) if e.kind == "guardrail"]


def test_verified_verdict_is_kept_and_the_check_is_traced() -> None:
    rec = recorder()

    out = check(rec, verdict())

    assert out == verdict(verified=True)
    (event,) = guardrails(rec)
    assert event.name == "verify:NCT00000001:inc-1"
    assert event.status == "ok"


def test_fabricated_criterion_quote_downgrades_to_unknown() -> None:
    rec = recorder()

    out = check(rec, verdict(criterion_quote="Prior bariatric surgery within 12 months"))

    assert out.outcome == "unknown"
    assert out.verified is False
    assert out.trace_event_id == "judge-step"
    (event,) = guardrails(rec)
    assert event.status == "failed"
    assert event.output is not None
    assert [f["field"] for f in event.output["failed"]] == ["criterion_quote"]
    assert event.output["original_outcome"] == "pass"
    assert event.note is not None and "criterion_quote" in event.note


def test_fabricated_patient_evidence_downgrades_to_unknown() -> None:
    rec = recorder()

    out = check(rec, verdict(outcome="fail", patient_evidence="Hospitalized for pancreatitis 2022"))

    assert (out.outcome, out.verified) == ("unknown", False)
    (event,) = guardrails(rec)
    assert event.output is not None
    assert [f["field"] for f in event.output["failed"]] == ["patient_evidence"]


def test_patient_evidence_may_come_from_the_rendered_facts() -> None:
    rec = recorder()

    out = check(rec, verdict(patient_evidence="labs.egfr: 48 mL/min/1.73m2"), note=None)

    assert (out.outcome, out.verified) == ("pass", True)


def test_pass_or_fail_without_patient_evidence_is_unverified() -> None:
    rec = recorder()

    out = check(rec, verdict(outcome="fail", patient_evidence=None))

    assert (out.outcome, out.verified) == ("unknown", False)


def test_unknown_without_patient_evidence_is_fine() -> None:
    rec = recorder()

    out = check(rec, verdict(outcome="unknown", patient_evidence=None))

    assert (out.outcome, out.verified) == ("unknown", True)
    (event,) = guardrails(rec)
    assert event.status == "ok"
