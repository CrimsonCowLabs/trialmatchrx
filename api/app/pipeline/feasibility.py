"""Feasibility simulator (SPEC.md pipeline 6): compiled predicates x cohort -> waterfall.

    cohort = Cohort.from_facts(list_of_patient_facts)       # once, at startup
    result = simulate(nct_id, criteria, cohort, overrides={"inc-2": 45})

Pure and deterministic: no LLM, no I/O, no tracing (a slider drag is not a decision worth a
trace event). The cohort is a pandas DataFrame, one row per patient; each predicate becomes one
vectorized column check, cached per predicate, so an override only recomputes its own column.

Counting rules, which differ from the matcher's on purpose (a cohort is screened in bulk, so
`unknown` has to land somewhere):
- Conditions and meds are a closed world: a Synthea record lists every diagnosis and active
  prescription, so a name it doesn't list is absent (`has` -> no, `not_has` -> yes).
- Missing data (no eGFR on file, pregnancy never recorded) is counted per step as `missing`.
  An inclusion needs evidence, so those patients drop; an exclusion needs evidence to exclude,
  so they stay.
- A criterion with no predicate is never applied and never silently passed: it is listed in
  `review_criteria`, and everyone left after the rules counts as `needs_review`.
"""

import operator
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from app.pipeline.evaluate import fold, name_pattern, predicate_names
from app.pipeline.predicate_fields import (
    LAB_UNITS,
    NUMERIC_OPS,
    VITAL_UNITS,
    InvalidPredicate,
    normalize_unit,
    validate_predicate,
)
from app.schemas import (
    Criterion,
    FeasibilityResult,
    LeaveOneOut,
    PatientFacts,
    Predicate,
    ReviewCriterion,
    WaterfallStep,
)

Mask = npt.NDArray[np.bool_]

_COMPARE: dict[str, Callable[[Any, Any], Any]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}
_CANONICAL = {"labs": LAB_UNITS, "vitals": VITAL_UNITS}
# Masks are ~2 KB per predicate at 1,000 patients; bounded because slider values are unbounded.
MAX_CACHED_CHECKS = 512
_LISTS = ("conditions", "meds")
_FLAGS = ("pregnant", "smoker")


class InvalidOverride(ValueError):
    """An override names an unknown criterion, one without a predicate, or a bad value."""


def _flag(value: bool | None) -> str | None:
    # Predicates carry booleans as "true" / "false" (Predicate.value has no bool).
    return None if value is None else str(value).lower()


def _row(facts: PatientFacts) -> dict[str, Any]:
    row: dict[str, Any] = {
        "age": float(facts.age) if facts.age is not None else np.nan,
        "sex": facts.sex,
        "pregnant": _flag(facts.pregnant),
        "smoker": _flag(facts.smoker),
        "conditions": "\n".join(fold(str(c.value)) for c in facts.conditions),
        "meds": "\n".join(fold(str(m.value)) for m in facts.meds),
    }
    for section in ("labs", "vitals"):
        for key, fact in getattr(facts, section).items():
            canonical = _CANONICAL[section].get(key)
            value = fact.value
            if canonical is None or isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if fact.unit is not None and normalize_unit(fact.unit) != normalize_unit(canonical):
                continue  # a reading in another unit is missing data, not a wrong number
            row[f"{section}.{key}"] = float(value)
    return row


class Cohort:
    """The cohort as one DataFrame, plus a per-predicate cache of (known, holds) masks."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self._checks: dict[str, tuple[Mask, Mask]] = {}

    @classmethod
    def from_facts(cls, patients: Sequence[PatientFacts]) -> "Cohort":
        return cls(pd.DataFrame([_row(f) for f in patients]))

    @property
    def size(self) -> int:
        return len(self.frame)

    def check(self, p: Predicate) -> tuple[Mask, Mask]:
        """Per patient: can the facts answer the predicate (`known`), and does it hold."""
        key = p.model_dump_json()
        if key not in self._checks:
            if len(self._checks) >= MAX_CACHED_CHECKS:
                # Every slider position is a new predicate; drop the oldest (insertion order).
                del self._checks[next(iter(self._checks))]
            self._checks[key] = self._check(p)
        return self._checks[key]

    def _check(self, p: Predicate) -> tuple[Mask, Mask]:
        n = self.size
        nothing: Mask = np.zeros(n, dtype=bool)
        head = p.field.partition(".")[0]
        if n == 0:
            return nothing, nothing  # an empty frame has no columns at all
        if head in _LISTS:
            # One regex over each patient's newline-joined names: the matcher's whole-word
            # rule (`mentions`), vectorized. A folded name has no newline, so no match spans two.
            names = [w for w in predicate_names(p.value) if w]
            if not names:
                return nothing, nothing  # an empty pattern would match everyone
            pattern = "|".join(name_pattern(w) for w in names)
            hit = self.frame[head].str.contains(pattern, regex=True).to_numpy(dtype=bool)
            return np.ones(n, dtype=bool), ~hit if p.op == "not_has" else hit
        if p.field not in self.frame.columns:
            return nothing, nothing  # nobody in the cohort has this lab / vital
        column = self.frame[p.field]
        if head in ("sex", *_FLAGS):
            known = column.notna().to_numpy(dtype=bool)
            return known, (column == p.value).to_numpy(dtype=bool) & known
        if p.op not in NUMERIC_OPS or isinstance(p.value, list | str):
            return nothing, nothing  # validate_predicate keeps these out at compile time
        values = column.to_numpy(dtype=float)
        known = ~np.isnan(values)
        with np.errstate(invalid="ignore"):
            holds = np.asarray(_COMPARE[p.op](values, float(p.value)), dtype=bool)
        return known, holds & known


def apply_overrides(
    criteria: Sequence[Criterion], overrides: Mapping[str, float | str | list[str]]
) -> list[Criterion]:
    """The criteria with each override's value swapped into its predicate (re-validated)."""
    by_id = {c.id: c for c in criteria}
    for crit_id in overrides:
        if crit_id not in by_id:
            raise InvalidOverride(f"no criterion {crit_id!r} in this trial")
        if by_id[crit_id].predicate is None:
            raise InvalidOverride(f"{crit_id} has no predicate to override")
    out = []
    for c in criteria:
        if c.id in overrides and c.predicate is not None:
            raw = {**c.predicate.model_dump(), "value": overrides[c.id]}
            try:
                predicate = validate_predicate(raw)
            except InvalidPredicate as exc:
                raise InvalidOverride(f"{c.id}: {exc}") from exc
            c = c.model_copy(update={"predicate": predicate})
        out.append(c)
    return out


def _passes(criterion: Criterion, known: Mask, holds: Mask) -> Mask:
    evidence = known & holds
    return evidence if criterion.type == "inclusion" else ~evidence


def simulate(
    nct_id: str,
    criteria: Sequence[Criterion],
    cohort: Cohort,
    overrides: Mapping[str, float | str | list[str]] | None = None,
) -> FeasibilityResult:
    """Waterfall, leave-one-out impact and needs-review count for one trial over the cohort.
    Raises InvalidOverride."""
    compiled = {c.id: c.predicate for c in criteria if c.predicate is not None}
    effective = apply_overrides(criteria, overrides or {})
    rules = [(c, c.predicate) for c in effective if c.predicate is not None]
    remaining: Mask = np.ones(cohort.size, dtype=bool)
    passes: list[Mask] = []
    waterfall: list[WaterfallStep] = []
    for c, predicate in rules:
        known, holds = cohort.check(predicate)
        passed = _passes(c, known, holds)
        passes.append(passed)
        waterfall.append(
            WaterfallStep(
                criterion_id=c.id,
                text=c.text,
                type=c.type,
                category=c.category,
                field=predicate.field,
                op=predicate.op,
                value=predicate.value,
                default_value=compiled[c.id].value,
                unit=predicate.unit,
                numeric=isinstance(predicate.value, float),  # a threshold: slider-able
                remaining=int((remaining & passed).sum()),
                dropped=int((remaining & ~passed).sum()),
                missing=int((remaining & ~known).sum()),
            )
        )
        remaining &= passed

    eligible = int(remaining.sum())
    leave_one_out = [
        LeaveOneOut(
            criterion_id=c.id,
            added_if_removed=_count_all(passes[:i] + passes[i + 1 :], cohort.size) - eligible,
        )
        for i, (c, _) in enumerate(rules)
    ]
    review = [
        ReviewCriterion(criterion_id=c.id, text=c.text, type=c.type)
        for c in criteria
        if c.predicate is None
    ]
    return FeasibilityResult(
        nct_id=nct_id,
        cohort_size=cohort.size,
        waterfall=waterfall,
        leave_one_out=leave_one_out,
        needs_review=eligible if review else 0,
        review_criteria=review,
    )


def _count_all(masks: list[Mask], size: int) -> int:
    """Patients who pass every mask (everyone, when there are none)."""
    everyone: Mask = np.ones(size, dtype=bool)
    for mask in masks:
        everyone &= mask
    return int(everyone.sum())
