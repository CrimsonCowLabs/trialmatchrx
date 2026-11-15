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
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.pipeline.predicate_fields import NUMERIC_OPS, normalize_unit
from app.schemas import Criterion, Fact, PatientFacts, Predicate, TraceStatus, Verdict
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
        case "==":
            return actual == target
    raise ValueError(f"op {op!r} is not numeric")  # callers check NUMERIC_OPS first


def _numeric(fact: Fact | None, label: str, p: Predicate) -> PredicateResult:
    if fact is None:
        return PredicateResult(None, None, f"no {label} in the patient facts")
    value = fact.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return PredicateResult(None, _evidence(fact, label), f"{label} is not a number")
    if (
        p.unit is not None
        and fact.unit is not None
        and normalize_unit(fact.unit) != normalize_unit(p.unit)
    ):
        return PredicateResult(
            None, _evidence(fact, label), f"{label} is in {fact.unit}, criterion uses {p.unit}"
        )
    if isinstance(p.value, list | str) or p.op not in NUMERIC_OPS:
        return PredicateResult(None, None, f"cannot compare {label} {p.op} {p.value!r}")
    holds = _compare(float(value), p.op, float(p.value))
    return PredicateResult(holds, _evidence(fact, label), f"{label} {value:g} {p.op} {p.value:g}")


def fold(text: str) -> str:
    """Lowercased, whitespace runs collapsed to one space: how names are compared."""
    return " ".join(text.lower().split())


def predicate_names(value: float | str | list[str]) -> list[str]:
    """The names a `has` / `not_has` / `in` predicate asks for, folded."""
    items = value if isinstance(value, list) else [str(value)]
    return [fold(v) for v in items]


def name_pattern(name: str) -> str:
    """Regex for a folded name as a whole-word match inside folded text."""
    return rf"\b{re.escape(name)}\b"


def mentions(text: str, name: str) -> bool:
    """Whole-word containment: "type 2 diabetes" is in "type 2 diabetes mellitus", "hiv" is
    not in "archive". `name` comes from `predicate_names`."""
    return re.search(name_pattern(name), fold(text)) is not None


def _membership(items: list[Fact], label: str, p: Predicate) -> PredicateResult:
    """`has` / `in` / `not_has` on conditions or meds.

    Only a listed name is evidence. A name the facts don't list is `holds=None` (unknown) in
    both directions: a note's silence about pancreatitis neither proves nor rules it out.
    """
    wanted = predicate_names(p.value)
    hits = [f for f in items if any(mentions(str(f.value), w) for w in wanted)]
    if not hits:
        listed = ", ".join(str(f.value) for f in items) or "none listed"
        return PredicateResult(None, None, f"{', '.join(wanted)} not among {label} ({listed})")
    evidence = "; ".join(_evidence(f, label) for f in hits)
    holds = p.op != "not_has"
    return PredicateResult(holds, evidence, f"{label} include {', '.join(wanted)}")


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
    return "pass" if met else "fail"


class Judge(Protocol):
    """Decides a criterion that has no predicate. Must trace its own work and return a Verdict
    whose `trace_event_id` points at the event that produced it (`judge.llm_judge`)."""

    async def __call__(
        self, nct_id: str, criterion: Criterion, facts: PatientFacts, rec: TraceRecorder
    ) -> Verdict: ...


def _traced_verdict(
    nct_id: str,
    criterion: Criterion,
    rec: TraceRecorder,
    *,
    outcome: Outcome,
    evidence: str | None,
    rationale: str,
    trace_input: dict[str, Any],
    trace_output: dict[str, Any],
    status: TraceStatus = "ok",
) -> Verdict:
    """Record one `rule:<nct>:<criterion id>` event and the Verdict that points at it."""
    event = rec.event(
        f"rule:{nct_id}:{criterion.id}",
        "rule",
        status=status,
        input={"criterion_id": criterion.id, "type": criterion.type, **trace_input},
        output={"outcome": outcome, **trace_output},
        note=f"{criterion.id}: {rationale}",
    )
    return Verdict(
        criterion_id=criterion.id,
        outcome=outcome,
        method="rule",
        criterion_quote=criterion.text,
        patient_evidence=evidence,
        rationale=rationale,
        verified=True,
        trace_event_id=event.id,
    )


async def no_judge(
    nct_id: str, criterion: Criterion, facts: PatientFacts, rec: TraceRecorder
) -> Verdict:
    """The fallback Judge when no judge model is available (no API key): `unknown`, recorded as
    a skipped `rule` event."""
    return _traced_verdict(
        nct_id,
        criterion,
        rec,
        outcome="unknown",
        evidence=None,
        rationale="needs judgment; no rule can decide it and no LLM judge is available",
        trace_input={"predicate": None},
        trace_output={},
        status="skipped",
    )


def rule_verdict(
    nct_id: str, criterion: Criterion, predicate: Predicate, facts: PatientFacts, rec: TraceRecorder
) -> Verdict:
    """Run a criterion's predicate and record it as one `rule` event."""
    result = check_predicate(predicate, facts)
    outcome = outcome_for(criterion, result)
    return _traced_verdict(
        nct_id,
        criterion,
        rec,
        outcome=outcome,
        evidence=result.evidence,
        rationale=f"{result.reason} -> {outcome} ({criterion.type})",
        trace_input={"predicate": predicate.model_dump(mode="json")},
        trace_output={"holds": result.holds, "evidence": result.evidence},
    )


async def evaluate_criterion(
    nct_id: str,
    criterion: Criterion,
    facts: PatientFacts,
    rec: TraceRecorder,
    *,
    judge: Judge = no_judge,
) -> Verdict:
    """One Verdict for one criterion: its predicate if it has one, else the judge. The verdict
    carries the criterion's access barrier flag."""
    if criterion.predicate is None:
        verdict = await judge(nct_id, criterion, facts, rec)
    else:
        verdict = rule_verdict(nct_id, criterion, criterion.predicate, facts, rec)
    return verdict.model_copy(update={"access_barrier": criterion.access_barrier})


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
