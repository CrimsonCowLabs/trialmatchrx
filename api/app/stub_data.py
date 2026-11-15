# HACK(demo): stub — everything in this module is fake and replaced milestone by milestone.
"""Fixed, schema-valid payloads for routes whose pipelines don't exist yet.

Every constant here is fake and synthetic. Each milestone replaces its piece:
patient/matches (M2), trial + criteria (M1), feasibility (M5), eval (M4).
"""

import datetime as dt

from app.schemas import (
    Criterion,
    EvalLatest,
    EvalRunSummary,
    Fact,
    FeasibilityResult,
    PatientFacts,
    Predicate,
    TrialDetail,
    TrialMatch,
    Verdict,
)

STUB_NCT = "NCT00000000"

# HACK(demo): stub — the SPEC demo patient (61M, T2D, HbA1c 8.4%, eGFR 48, metformin, Sacramento).
STUB_PATIENT = PatientFacts(
    age=61,
    sex="male",
    conditions=[Fact(value="type 2 diabetes mellitus", source_span="type 2 diabetes")],
    labs={
        "hba1c": Fact(value=8.4, unit="%", source_span="HbA1c 8.4%"),
        "egfr": Fact(value=48, unit="mL/min/1.73m2", source_span="eGFR 48"),
    },
    vitals={},
    meds=[Fact(value="metformin", source_span="on metformin")],
    pregnant=False,
    smoker=None,
    lat=38.5816,
    lon=-121.4944,
)

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


# HACK(demo): stub — fake waterfall; the eGFR threshold moves the count so the UI reacts.
def stub_feasibility(nct_id: str, egfr_min: float) -> FeasibilityResult:
    cohort = 1000
    after_dx = 412
    after_egfr = int(after_dx * max(0.0, min(1.0, (90 - egfr_min) / 60)))
    return FeasibilityResult(
        nct_id=nct_id,
        cohort_size=cohort,
        waterfall=[
            {
                "criterion_id": "dx",
                "text": "Type 2 diabetes",
                "remaining": after_dx,
                "dropped": cohort - after_dx,
            },
            {
                "criterion_id": "inc-1",
                "text": f"eGFR >= {egfr_min:g}",
                "remaining": after_egfr,
                "dropped": after_dx - after_egfr,
            },
        ],
        leave_one_out=[
            {"criterion_id": "dx", "added_if_removed": 0},
            {"criterion_id": "inc-1", "added_if_removed": after_dx - after_egfr},
        ],
        needs_review=1,
    )


# HACK(demo): stub — made-up eval numbers until `make eval` writes eval_runs (M4).
STUB_EVAL = EvalLatest(
    metrics={"ndcg@10": 0.0, "p@10": 0.0, "accuracy": 0.0},
    baseline={"ndcg@10": 0.0, "p@10": 0.0, "accuracy": 0.0},
    compile_rate=None,
    sample_size=0,
    history=[
        EvalRunSummary(
            id="stub",
            created_at=dt.datetime(2026, 11, 11, tzinfo=dt.UTC),
            git_sha=None,
            prompt_version=None,
            metrics={"ndcg@10": 0.0, "p@10": 0.0, "accuracy": 0.0},
        )
    ],
)
