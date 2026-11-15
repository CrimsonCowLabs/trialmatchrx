"""Matcher, rule half (SPEC.md pipeline 4): Criterion x PatientFacts -> Verdict, pure Python.

    verdict = await evaluate_criterion(nct_id, criterion, facts, rec)
    verdicts = await evaluate_trial(nct_id, criteria, facts, rec, judge=my_judge)

`outcome` is relative to eligibility: `pass` = fine on this criterion, `fail` = disqualifies,
`unknown` = the data needed is missing. Predicates state the criterion as written; exclusions
are inverted here. A missing fact gives `unknown`, never `fail`.

Every rule evaluation is one `rule` trace event named `rule:<nct>:<criterion id>`, and the
Verdict's `trace_event_id` points at it.
"""

import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol

from app.pipeline.predicate_fields import NUMERIC_OPS
from app.schemas import Criterion, Fact, PatientFacts, Predicate, Verdict
from app.trace.recorder import TraceRecorder

Outcome = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class PredicateResult:
    """Whether the predicate, as written, holds for the patient.

    `holds` is None when the facts can't answer it. `evidence` is what the answer rests on
    (the fact's source span, or a rendering of it).
    """

    holds: bool | None
    evidence: str | None
    reason: str
    # True when the answer rests on a name *not* being in conditions / meds. A note that
    # doesn't mention something is not proof it's absent, so this can clear a criterion but
    # never disqualify on it.
    from_absence: bool = False


def _norm_unit(unit: str | None) -> str | None:
    return None if unit is None else unit.replace("²", "2").replace(" ", "").lower()


def _evidence(fact: Fact, label: str) -> str:
    if fact.source_span:
        return fact.source_span
    unit = f" {fact.unit}" if fact.unit else ""
    return f"{label} {fact.value}{unit}"


def _compare(actual: float, op: str, target: float) -> bool:
    match op:
        case ">=":
            return actual >= target
        case "<=":
            return actual <= target
        case ">":
            return actual > target
        case "<":
            return actual < target
    return actual == target


def _numeric(fact: Fact | None, label: str, p: Predicate) -> PredicateResult:
    if fact is None:
        return PredicateResult(None, None, f"no {label} in the patient facts")
    value = fact.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return PredicateResult(None, _evidence(fact, label), f"{label} is not a number")
    if p.unit is not None and fact.unit is not None and _norm_unit(fact.unit) != _norm_unit(p.unit):
        return PredicateResult(
            None, _evidence(fact, label), f"{label} is in {fact.unit}, criterion uses {p.unit}"
        )
    if isinstance(p.value, list | str) or p.op not in NUMERIC_OPS:
        return PredicateResult(None, None, f"cannot compare {label} {p.op} {p.value!r}")
    holds = _compare(float(value), p.op, float(p.value))
    return PredicateResult(holds, _evidence(fact, label), f"{label} {value:g} {p.op} {p.value:g}")


def _names(value: float | str | list[str]) -> list[str]:
    items = value if isinstance(value, list) else [str(value)]
    return [" ".join(v.lower().split()) for v in items]


def _membership(items: list[Fact], label: str, p: Predicate) -> PredicateResult:
    """`has` / `in` / `not_has` on conditions or meds. A wanted name matches a listed fact
    when it is contained in it ("type 2 diabetes" matches "type 2 diabetes mellitus")."""
    if not items:
        return PredicateResult(None, None, f"no {label} in the patient facts")
    wanted = _names(p.value)
    hits = [f for f in items if any(w in " ".join(str(f.value).lower().split()) for w in wanted)]
    present = bool(hits)
    holds = not present if p.op == "not_has" else present
    if present:
        evidence = "; ".join(_evidence(f, label) for f in hits)
        return PredicateResult(holds, evidence, f"{label} include {', '.join(wanted)}")
    listed = ", ".join(str(f.value) for f in items)
    reason = f"{', '.join(wanted)} not among {label} ({listed})"
    return PredicateResult(holds, None, reason, from_absence=True)


def check_predicate(p: Predicate, facts: PatientFacts) -> PredicateResult:
    """Evaluate one predicate against the facts. Pure: no tracing, no I/O."""
    head, _, key = p.field.partition(".")
    if head == "labs":
        return _numeric(facts.labs.get(key), key, p)
    if head == "vitals":
        return _numeric(facts.vitals.get(key), key, p)
    if head == "age":
        age = None if facts.age is None else Fact(value=facts.age, unit="years")
        return _numeric(age, "age", p)
    if head == "sex":
        if facts.sex is None:
            return PredicateResult(None, None, "sex not recorded")
        return PredicateResult(facts.sex == p.value, f"sex {facts.sex}", f"sex is {facts.sex}")
    if head in ("conditions", "meds"):
        return _membership(getattr(facts, head), head, p)
    if head in ("pregnant", "smoker"):
        flag: bool | None = getattr(facts, head)
        if flag is None:
            return PredicateResult(None, None, f"{head} not recorded")
        wanted = str(p.value).lower() == "true"
        return PredicateResult(flag == wanted, f"{head}: {flag}", f"{head} is {flag}")
    # validate_predicate keeps these out at compile time; never let one sink a whole trial.
    return PredicateResult(None, None, f"no rule for field {p.field!r}")


def outcome_for(criterion: Criterion, result: PredicateResult) -> Outcome:
    """Map 'does the predicate hold' to eligibility: exclusions are inverted."""
    if result.holds is None:
        return "unknown"
    met = result.holds if criterion.type == "inclusion" else not result.holds
    if not met and result.from_absence:
        return "unknown"
    return "pass" if met else "fail"


class Judge(Protocol):
    """Decides a criterion that has no predicate. Must trace its own work and return a Verdict
    whose `trace_event_id` points at the event that produced it (issue #6 plugs the LLM judge
    in here)."""

    async def __call__(
        self, nct_id: str, criterion: Criterion, facts: PatientFacts, rec: TraceRecorder
    ) -> Verdict: ...


async def no_judge(
    nct_id: str, criterion: Criterion, facts: PatientFacts, rec: TraceRecorder
) -> Verdict:
    """The default Judge: `unknown`, recorded as a skipped `rule` event."""
    # HACK(demo): no LLM judge yet (issue #6); criteria without a predicate are `unknown`.
    rationale = "needs judgment; no rule can decide it and the LLM judge is not wired in yet"
    event = rec.event(
        f"rule:{nct_id}:{criterion.id}",
        "rule",
        status="skipped",
        input={"criterion_id": criterion.id, "type": criterion.type, "predicate": None},
        output={"outcome": "unknown"},
        note=f"{criterion.id}: no predicate -> unknown",
    )
    return Verdict(
        criterion_id=criterion.id,
        outcome="unknown",
        method="rule",
        criterion_quote=criterion.text,
        patient_evidence=None,
        rationale=rationale,
        verified=True,
        trace_event_id=event.id,
    )


def rule_verdict(
    nct_id: str, criterion: Criterion, predicate: Predicate, facts: PatientFacts, rec: TraceRecorder
) -> Verdict:
    """Run a criterion's predicate and record it as one `rule` event."""
    result = check_predicate(predicate, facts)
    outcome = outcome_for(criterion, result)
    rationale = f"{result.reason} -> {outcome} ({criterion.type})"
    event = rec.event(
        f"rule:{nct_id}:{criterion.id}",
        "rule",
        input={
            "criterion_id": criterion.id,
            "type": criterion.type,
            "predicate": predicate.model_dump(mode="json"),
        },
        output={"outcome": outcome, "holds": result.holds, "evidence": result.evidence},
        note=f"{criterion.id}: {rationale}",
    )
    return Verdict(
        criterion_id=criterion.id,
        outcome=outcome,
        method="rule",
        criterion_quote=criterion.text,
        patient_evidence=result.evidence,
        rationale=rationale,
        verified=True,
        trace_event_id=event.id,
    )


async def evaluate_criterion(
    nct_id: str,
    criterion: Criterion,
    facts: PatientFacts,
    rec: TraceRecorder,
    *,
    judge: Judge = no_judge,
) -> Verdict:
    """One Verdict for one criterion: its predicate if it has one, else the judge."""
    if criterion.predicate is None:
        return await judge(nct_id, criterion, facts, rec)
    return rule_verdict(nct_id, criterion, criterion.predicate, facts, rec)


async def evaluate_trial(
    nct_id: str,
    criteria: list[Criterion],
    facts: PatientFacts,
    rec: TraceRecorder,
    *,
    judge: Judge = no_judge,
) -> list[Verdict]:
    """Verdicts for every criterion, in criterion order. Criteria run concurrently, so a
    judge that calls an LLM should bound itself (SPEC.md: Semaphore(8))."""
    return list(
        await asyncio.gather(
            *(evaluate_criterion(nct_id, c, facts, rec, judge=judge) for c in criteria)
        )
    )
