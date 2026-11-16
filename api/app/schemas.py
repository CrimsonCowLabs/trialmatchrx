"""All shared Pydantic contracts, in one file on purpose (SPEC.md "Data contracts and API").

The first block mirrors SPEC.md field for field and is frozen after milestone 0. Change it only
through a PR that also runs `make types` to regenerate web/lib/api-types.ts.
The second block holds the request/response models for the API table.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------------
# Frozen contracts (SPEC.md)
# --------------------------------------------------------------------------------------------

TraceKind = Literal["run", "step", "llm", "tool", "rule", "guardrail", "error"]
TraceStatus = Literal["started", "ok", "failed", "skipped"]


class TraceEvent(BaseModel):
    id: str  # uuid
    run_id: str
    parent_id: str | None  # nests steps: run > trial > criterion > llm call
    seq: int  # monotonic per run, for ordering + replay
    kind: TraceKind
    name: str  # "compile_criteria", "judge:NCT05...:inc-3", "search_trials"
    status: TraceStatus
    started_at: dt.datetime
    ended_at: dt.datetime | None
    input: dict[str, Any] | None  # prompt messages / tool args / rule + facts
    output: dict[str, Any] | None  # parsed output / tool result / rule result
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    cache_hit: bool = False
    note: str | None  # human-readable one-liner shown in the timeline


class Fact(BaseModel):
    value: str | float | bool
    unit: str | None = None
    # `dt.date` because a field named `date` would shadow the `date` type in the class body.
    date: dt.date | None = None
    source_span: str | None = None  # verbatim text from the note, for verification


class PatientFacts(BaseModel):
    age: int | None
    sex: Literal["female", "male"] | None
    conditions: list[Fact]  # value = condition name; SNOMED code optional
    labs: dict[str, Fact]  # keys: hba1c, egfr, uacr, ldl, potassium ...
    vitals: dict[str, Fact]  # bmi, sbp, dbp
    meds: list[Fact]  # value = drug name; plus drug_class if known
    pregnant: bool | None
    smoker: bool | None
    lat: float | None
    lon: float | None
    place: str | None = None  # where the patient lives, e.g. "Sacramento, CA"; display only


class Predicate(BaseModel):
    field: str  # dotted path into PatientFacts
    op: Literal[">=", "<=", ">", "<", "==", "in", "has", "not_has"]
    value: float | str | list[str]
    unit: str | None = None


# A criterion that shuts people out for a reason other than health (issue #53). Set by the
# rule-based classifier in pipeline/access_barriers.py from the verbatim text; None = no barrier.
AccessBarrier = Literal["language", "visit_burden", "technology", "support"]


class Criterion(BaseModel):
    id: str  # "inc-3", "exc-7"
    type: Literal["inclusion", "exclusion"]
    text: str  # verbatim from the trial
    category: Literal[
        "demographic", "diagnosis", "lab", "medication", "history", "procedure", "other"
    ]
    predicate: Predicate | None
    needs_judgment: bool
    access_barrier: AccessBarrier | None = None


class Verdict(BaseModel):
    criterion_id: str
    outcome: Literal["pass", "fail", "unknown"]
    method: Literal["rule", "llm"]
    criterion_quote: str
    patient_evidence: str | None
    rationale: str
    verified: bool
    trace_event_id: str  # powers the "Why?" link
    access_barrier: AccessBarrier | None = None  # the criterion's, copied for the results page


Tier = Literal["likely", "needs_info", "ineligible"]


class TrialMatch(BaseModel):
    nct_id: str
    title: str
    phase: str | None
    distance_mi: float | None
    tier: Tier
    verdicts: list[Verdict]
    counts: dict[str, int]  # pass / fail / unknown


class WaterfallStep(BaseModel):
    """One rule of the feasibility waterfall. SPEC.md's {criterion_id, text, remaining, dropped},
    plus what the threshold sliders need."""

    criterion_id: str
    text: str
    type: Literal["inclusion", "exclusion"]
    category: str
    field: str
    op: str
    value: float | str | list[str]  # after overrides
    default_value: float | str | list[str]  # as compiled
    unit: str | None
    numeric: bool  # a numeric threshold: gets a slider
    remaining: int
    dropped: int
    missing: int  # patients with no data for it: dropped on an inclusion, kept on an exclusion
    access_barrier: AccessBarrier | None = None


class LeaveOneOut(BaseModel):
    criterion_id: str
    added_if_removed: int


class ReviewCriterion(BaseModel):
    """A criterion with no predicate: never applied, never counted as passed."""

    criterion_id: str
    text: str
    type: Literal["inclusion", "exclusion"]
    access_barrier: AccessBarrier | None = None


class FeasibilityResult(BaseModel):
    nct_id: str
    cohort_size: int
    waterfall: list[WaterfallStep]  # SPEC.md: list[dict] {criterion_id, text, remaining, dropped}
    leave_one_out: list[LeaveOneOut]
    needs_review: int  # patients left after the rules who still face review_criteria
    review_criteria: list[ReviewCriterion]


# --------------------------------------------------------------------------------------------
# API request / response models (SPEC.md API table)
# --------------------------------------------------------------------------------------------

RunKind = Literal["match", "closer", "compile", "trial"]
RunStatus = Literal["running", "done", "failed"]


class MatchRequest(BaseModel):
    note: str | None = None
    fhir_bundle: dict[str, Any] | None = None
    condition: str
    # HACK(demo): 100 mi, the radius `make seed` caches (config.ctgov_seed_radius_mi), not
    # SPEC.md's 50 mi. SPEC's 50 mi stays the meaning of "near": the UI warns on trials whose
    # nearest site is farther (web/lib/match-results.ts NEAR_RADIUS_MI) instead of dropping them.
    radius_mi: int = 100


class RunStarted(BaseModel):
    run_id: str


class RunTotals(BaseModel):
    """Header strip of the trace panel. Computed from the run's trace events."""

    llm_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_hits: int
    guardrail_trips: int  # `guardrail` events that failed (bad quote, invalid predicate, ...)
    wall_time_s: float | None


class Followup(BaseModel):
    """One follow-up: what resolves one `unknown` criterion."""

    criterion_id: str = Field(description="Id of the unknown criterion this resolves, e.g. inc-7")
    kind: Literal["test", "question"] = Field(
        description="test = a lab or exam to order; question = something to ask the patient or "
        "their clinician"
    )
    action: str = Field(description="The test to order or the question to ask, in one sentence")
    why: str = Field(description="How the answer decides the criterion")


class CoordinatorEmail(BaseModel):
    to: str | None = Field(
        description="The trial contact's email address from get_trial_contacts; null if none"
    )
    subject: str
    body: str = Field(description="Plain text, under 200 words, no patient name or identifiers")


class PatientSummary(BaseModel):
    en: str = Field(description="English, 6th-grade reading level, under 120 words")
    es: str = Field(description="The same summary in Spanish, 6th-grade reading level")


class CloserOutput(BaseModel):
    """Next steps for one patient and one trial: follow-ups for every unknown criterion, an
    email to the study coordinator, and a plain-language summary for the patient."""

    nct_id: str
    followups: list[Followup] = Field(description="One per unknown criterion, in trial order")
    coordinator_email: CoordinatorEmail
    patient_summary: PatientSummary


class RunSummary(BaseModel):
    run_id: str
    kind: RunKind
    status: RunStatus
    patient: PatientFacts | None  # None until the patient has been parsed
    matches: list[TrialMatch]
    totals: RunTotals
    closer: CloserOutput | None = None  # a closer run's answer, once it is done
    patient_label: str | None = None  # "58 F", as on RunListItem; None until the patient is parsed
    condition: str | None = None  # the match request's condition; None for a closer run
    # A closer run's match run and its trial's title (from that run's TrialMatch); None for a
    # match run, or when the match run is gone. A closer run's patient_label is that run's too.
    source_run_id: str | None = None
    trial_title: str | None = None
    max_unknowns_for_likely: int  # the tier rule: "likely" = no fails, at most this many unknown


class TierCounts(BaseModel):
    """How many of a run's matches landed in each tier."""

    likely: int = 0
    needs_info: int = 0
    ineligible: int = 0


class RunListItem(BaseModel):
    """One row of the runs browser. Derived from the run row alone (no trace events, so no
    totals): `patient_label` is e.g. "58 F" once the patient is parsed, `tier_counts` has
    likely / needs_info / ineligible (zeros until there are matches)."""

    run_id: str
    kind: RunKind
    status: RunStatus
    created_at: dt.datetime
    ended_at: dt.datetime | None
    patient_label: str | None
    tier_counts: TierCounts


class RunStats(BaseModel):
    """What recent finished (`done`) match runs took, for the match form's hint. From stored
    runs and their trace events; every figure is None when `runs` is 0."""

    runs: int  # finished match runs summarised (the most recent, at most `limit`)
    wall_time_min_s: float | None
    wall_time_max_s: float | None
    cost_usd_median: float | None  # median of each run's summed `llm` event cost


class RunDone(BaseModel):
    """Payload of the final `done` SSE event."""

    run_id: str
    status: RunStatus


class TrialDetail(BaseModel):
    nct_id: str
    title: str
    phase: str | None
    overall_status: str | None
    eligibility_text: str | None
    criteria: list[Criterion]


class TrialListItem(BaseModel):
    """One row of the trials browser: a cached trial and whether its criteria are compiled."""

    nct_id: str
    title: str
    phase: str | None
    overall_status: str | None
    compiled: bool
    criteria_count: int


class CompileRequest(BaseModel):
    force: bool = False


class FeasibilityRequest(BaseModel):
    overrides: dict[str, float | str | list[str]] = Field(default_factory=dict)


class CloserRequest(BaseModel):
    run_id: str
    nct_id: str


# The first-time guide's steps (SPEC.md "First-time user guide"), in the order the guide shows.
GuideStep = Literal["als", "ipf", "ipf_flip", "pah", "feasibility"]


class GuidePin(BaseModel):
    """One pinned guide step: the run (and, for some steps, the trial) its links open."""

    step: GuideStep
    run_id: str | None
    nct_id: str | None
    # True when `run_id` names a run in the runs table (any status); False when it doesn't
    # or there is no `run_id`. A `feasibility` pin carries only `nct_id`, so it is False
    # there; the web side keys that step off `nct_id`.
    run_exists: bool


EvalSystem = Literal["bm25", "matcher"]


class EvalRunSummary(BaseModel):
    id: str
    created_at: dt.datetime
    system: EvalSystem  # what was scored: the BM25 baseline or the matcher
    git_sha: str | None
    prompt_version: str | None
    sample_size: int  # judged (topic, trial) pairs scored
    metrics: dict[str, float]


class EvalLatest(BaseModel):
    metrics: dict[str, float]  # ndcg@10, p@10, accuracy, compile_rate (latest matcher run, or {})
    baseline: dict[str, float]  # BM25: ndcg@10, p@10, accuracy ({} until `make eval`)
    compile_rate: float | None  # latest matcher run: share of criteria with a predicate
    compile_rate_target: float  # share the compiler aims for (settings: SPEC.md "about 60%")
    sample_size: int  # judged (topic, trial) pairs in the fixed TREC sample
    topics: int  # TREC topics in the sample
    dropped: int  # sampled trials dropped (gone, merged into another record, or no criteria)
    history: list[EvalRunSummary]  # every run, newest first


class Health(BaseModel):
    ok: bool
    demo_mode: str
    model_ids: dict[str, str]
    # DEMO_MODE=replay: the demo patient ids with both a match and a closer recording.
    demo_patients: list[str] = []


# Accounts (SPEC.md "Marketing and accounts"). A failed sign-in answers with one of these two
# messages whatever went wrong (unknown email, wrong password, disabled account, no password).
LOGIN_FAILED = "Email or password is incorrect"
LOGIN_THROTTLED = "Try again in a few minutes"


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)  # not checked as an address: a miss is the same 401
    password: str = Field(max_length=1024)


class Me(BaseModel):
    """The signed-in account: `GET /api/auth/me` and a successful sign-in. Later tickets add
    fields (passkeys, the account page) rather than reshaping it."""

    id: str
    email: str
    has_password: bool  # false for a passkey-only account
    created_at: dt.datetime


# Invites (SPEC.md "Marketing and accounts", Accounts): why an invite link can't be used, as
# the invite page shows it.
INVITE_UNKNOWN = "This invite link isn't valid. Check that you copied all of it."
INVITE_EXPIRED = "This invite link has expired. Ask the team for a new one."
INVITE_USED = "This invite link has already been used. Sign in instead."
INVITE_ACCOUNT_EXISTS = "There's already an account for this email. Sign in instead."


class InviteInfo(BaseModel):
    """A usable invite: `GET /api/auth/invites/{token}`, for the invite page."""

    email: str
    expires_at: dt.datetime


class AcceptInviteRequest(BaseModel):
    """Accept an invite by setting a password. Passkeys (#4) will add the other way in (the
    spec allows a passkey, a password, or both)."""

    password: str = Field(max_length=1024)
