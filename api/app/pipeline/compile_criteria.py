"""Criteria compiler: a trial's eligibility module -> list[Criterion] (SPEC.md pipeline 3)."""

import re
from typing import Any

from app.schemas import Criterion, Predicate

# --------------------------------------------------------------------------------------------
# Age and sex: deterministic, from the structured fields
# --------------------------------------------------------------------------------------------

_AGE_UNITS_PER_YEAR = {
    "year": 1.0,
    "month": 12.0,
    "week": 52.0,
    "day": 365.25,
    "hour": 365.25 * 24,
    "minute": 365.25 * 24 * 60,
}
_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(year|month|week|day|hour|minute)s?\s*$", re.I)


def parse_age_years(raw: str | None) -> float | None:
    """ClinicalTrials.gov age ("18 Years", "6 Months", "N/A") -> years, or None."""
    if not raw:
        return None
    m = _AGE_RE.match(raw)
    if m is None:
        return None
    years = float(m.group(1)) / _AGE_UNITS_PER_YEAR[m.group(2).lower()]
    return round(years, 2)


def _age_criterion(crit_id: str, label: str, raw: str, op: str) -> Criterion:
    years = parse_age_years(raw)
    predicate = (
        None
        if years is None
        else Predicate.model_validate({"field": "age", "op": op, "value": years, "unit": "years"})
    )
    return Criterion(
        id=crit_id,
        type="inclusion",
        text=f"{label}: {raw}",
        category="demographic",
        predicate=predicate,
        needs_judgment=predicate is None,
    )


def structured_criteria(eligibility: dict[str, Any]) -> list[Criterion]:
    """Age and sex criteria from minimumAge / maximumAge / sex. No LLM.

    Ids are fixed (`inc-age-min`, `inc-age-max`, `inc-sex`) so overrides and verdicts can
    name them without knowing how many LLM criteria a trial has.
    """
    out: list[Criterion] = []
    for crit_id, key, label, op in (
        ("inc-age-min", "minimumAge", "Minimum age", ">="),
        ("inc-age-max", "maximumAge", "Maximum age", "<="),
    ):
        raw = eligibility.get(key)
        if raw and raw.strip().upper() != "N/A":
            out.append(_age_criterion(crit_id, label, raw, op))
    sex = (eligibility.get("sex") or "ALL").upper()
    if sex in ("FEMALE", "MALE"):
        out.append(
            Criterion(
                id="inc-sex",
                type="inclusion",
                text=f"Sex: {sex}",
                category="demographic",
                predicate=Predicate(field="sex", op="==", value=sex.lower()),
                needs_judgment=False,
            )
        )
    return out
