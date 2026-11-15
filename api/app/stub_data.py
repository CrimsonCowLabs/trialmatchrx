# HACK(demo): stub — everything in this module is fake and replaced milestone by milestone.
"""Fixed, schema-valid payloads for routes whose pipelines don't exist yet.

Every constant here is fake and synthetic. Each milestone replaces its piece:
patient/matches (M2), trial + criteria (M1). Eval (M4) reads eval_runs; feasibility (M5)
runs over the cohort.
"""

from app.schemas import (
    Criterion,
    Predicate,
    TrialDetail,
    TrialMatch,
    Verdict,
)

STUB_NCT = "NCT00000000"

# HACK(demo): stub — two hand-written criteria, one with a predicate, one needing judgment.
STUB_CRITERIA = [
    Criterion(
        id="inc-1",
        type="inclusion",
        text="eGFR >= 45 mL/min/1.73m2",
        category="lab",
        predicate=Predicate(field="labs.egfr", op=">=", value=45, unit="mL/min/1.73m2"),
        needs_judgment=False,
    ),
    Criterion(
        id="exc-1",
        type="exclusion",
        text="History of diabetic ketoacidosis within the past 6 months",
        category="history",
        predicate=None,
        needs_judgment=True,
    ),
]

# HACK(demo): stub — one fake trial returned for every NCT id.
STUB_TRIAL = TrialDetail(
    nct_id=STUB_NCT,
    title="Stub trial: SGLT2 inhibitor in T2D with CKD",
    phase="PHASE3",
    overall_status="RECRUITING",
    eligibility_text="Inclusion Criteria:\n* eGFR >= 45 mL/min/1.73m2\n\nExclusion Criteria:\n"
    "* History of diabetic ketoacidosis within the past 6 months",
    criteria=STUB_CRITERIA,
)


# HACK(demo): stub — one ranked trial whose verdicts point at a real event of the run.
def stub_matches(trace_event_id: str) -> list[TrialMatch]:
    return [
        TrialMatch(
            nct_id=STUB_NCT,
            title=STUB_TRIAL.title,
            phase=STUB_TRIAL.phase,
            distance_mi=4.2,
            tier="likely",
            verdicts=[
                Verdict(
                    criterion_id="inc-1",
                    outcome="pass",
                    method="rule",
                    criterion_quote="eGFR >= 45 mL/min/1.73m2",
                    patient_evidence="eGFR 48",
                    rationale="48 >= 45",
                    verified=True,
                    trace_event_id=trace_event_id,
                ),
                Verdict(
                    criterion_id="exc-1",
                    outcome="unknown",
                    method="llm",
                    criterion_quote="History of diabetic ketoacidosis within the past 6 months",
                    patient_evidence=None,
                    rationale="The note does not mention ketoacidosis.",
                    verified=True,
                    trace_event_id=trace_event_id,
                ),
            ],
            counts={"pass": 1, "fail": 0, "unknown": 1},
        )
    ]
