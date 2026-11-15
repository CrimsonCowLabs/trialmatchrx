"""The predicate vocabulary: which PatientFacts paths a Predicate may name, and how.

The compile prompt is rendered from this module (`describe_vocabulary`), and every predicate the
LLM writes is checked here (`validate_predicate`), so the prompt and the check can't drift.
"""

from collections.abc import Mapping
from typing import Any, Literal

from app.schemas import Predicate

FieldKind = Literal["numeric", "list", "sex", "bool"]

# Top-level PatientFacts fields a predicate may name. `labs` / `vitals` need a key.
# lat / lon are left out on purpose: distance is a ranking input, not a criterion.
FIELD_KINDS: dict[str, FieldKind] = {
    "age": "numeric",
    "sex": "sex",
    "conditions": "list",
    "meds": "list",
    "pregnant": "bool",
    "smoker": "bool",
    "labs": "numeric",
    "vitals": "numeric",
}

# Canonical keys and units. A predicate must use (or omit) the canonical unit; the LLM converts.
LAB_UNITS: dict[str, str] = {
    "hba1c": "%",
    "egfr": "mL/min/1.73m2",
    "uacr": "mg/g",
    "upcr": "mg/g",
    "potassium": "mmol/L",
    "ldl": "mg/dL",
    "creatinine": "mg/dL",
    "albumin": "g/dL",
    "alt": "U/L",
    "hscrp": "mg/L",
    # Pulmonary function, ALS and pulmonary-hypertension measures (the ALS / IPF / PAH demo).
    "fvc_pct": "% predicted",
    "fev1_pct": "% predicted",
    "fev1_fvc": "ratio",  # FEV1/FVC as a fraction, 0-1 (70% -> 0.70)
    "svc_pct": "% predicted",
    "dlco_pct": "% predicted",
    "alsfrs_r": "points",  # ALSFRS-R total, 0-48
    "six_mwd": "m",  # 6-minute walk distance
    "pvr": "WU",  # pulmonary vascular resistance, Wood units (80 dyn*s/cm5 = 1 WU)
    "pcwp": "mmHg",  # pulmonary capillary wedge pressure
}
VITAL_UNITS: dict[str, str] = {
    "bmi": "kg/m2",
    "sbp": "mmHg",
    "dbp": "mmHg",
    "weight": "kg",
}
_KEYED: dict[str, Mapping[str, str]] = {"labs": LAB_UNITS, "vitals": VITAL_UNITS}

# Other spellings accepted for a canonical unit (both sides through `normalize_unit`). "" is a
# reading written with no unit, allowed only where the unit is a count or a ratio.
UNIT_ALIASES: dict[str, frozenset[str]] = {
    "%predicted": frozenset({"%", "%pred", "%ofpredicted", "percentpredicted", "%pp"}),
    "ratio": frozenset({"", "fraction"}),
    "points": frozenset({"", "point", "pts", "pt", "score"}),
    "m": frozenset({"meter", "meters", "metre", "metres"}),
    "wu": frozenset({"woodunit", "woodunits"}),
}

# Plausible bounds (inclusive, canonical unit) for the keys where a wrong unit is easy to miss:
# a % where a fraction belongs, feet for metres, dyn*s/cm5 for Wood units. A reading outside is
# dropped by the note parser's `range` guardrail.
LAB_RANGES: dict[str, tuple[float, float]] = {
    "fvc_pct": (5, 200),
    "fev1_pct": (5, 200),
    "fev1_fvc": (0.1, 1.0),
    "svc_pct": (5, 200),
    "dlco_pct": (5, 200),
    "alsfrs_r": (0, 48),
    "six_mwd": (0, 1000),
    "pvr": (0, 40),
    "pcwp": (0, 60),
}

NUMERIC_OPS = (">=", "<=", ">", "<", "==")


class InvalidPredicate(ValueError):
    """The predicate names a field, op, value or unit PatientFacts can't answer."""


def normalize_unit(unit: str) -> str:
    """`mL/min/1.73 m²` and `ml/min/1.73m2` compare equal."""
    return unit.replace("²", "2").replace(" ", "").lower()


def units_match(unit: str | None, canonical: str) -> bool:
    """True when `unit` is `canonical` or an accepted alias of it. No unit matches only a
    canonical unit that may be written bare (a ratio, a score)."""
    want = normalize_unit(canonical)
    got = normalize_unit(unit or "")
    return got == want or got in UNIT_ALIASES.get(want, frozenset())


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidPredicate(f"value must be a number, got {value!r}")
    return float(value)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPredicate(f"value must be a non-empty string, got {value!r}")
    return value.strip().lower()


def _numeric(field: str, op: str, value: Any, unit: str | None, canonical: str) -> Predicate:
    if op not in NUMERIC_OPS:
        raise InvalidPredicate(f"op {op!r} not allowed on {field}; use one of {NUMERIC_OPS}")
    number = _number(value)
    if unit is not None and not units_match(unit, canonical):
        raise InvalidPredicate(f"unit {unit!r} on {field} must be {canonical!r}")
    return Predicate(field=field, op=op, value=number, unit=canonical)


def validate_predicate(raw: Mapping[str, Any]) -> Predicate:
    """Check a draft predicate against PatientFacts and return it normalized.

    Raises InvalidPredicate with a human-readable reason (recorded in the trace).
    """
    field = str(raw.get("field") or "")
    op = str(raw.get("op") or "")
    value = raw.get("value")
    unit = raw.get("unit")
    head, *rest = field.split(".")
    kind = FIELD_KINDS.get(head)
    if kind is None:
        raise InvalidPredicate(f"{field!r} is not a PatientFacts field")

    if head in _KEYED:
        if len(rest) != 1:
            raise InvalidPredicate(f"{field!r}: {head} needs a key, like {head}.<key>")
        units = _KEYED[head]
        if rest[0] not in units:
            noun = "lab" if head == "labs" else "vital"
            raise InvalidPredicate(f"unknown {noun} {rest[0]!r}; known: {sorted(units)}")
        return _numeric(field, op, value, unit, units[rest[0]])
    if rest:
        raise InvalidPredicate(f"{field!r} is not a PatientFacts field")

    if kind == "numeric":  # age
        return _numeric(field, op, value, unit, "years")
    if kind == "list":
        if op in ("has", "not_has"):
            return Predicate(field=field, op=op, value=_text(value))
        if op == "in":
            if not isinstance(value, list) or not value:
                raise InvalidPredicate(f"'in' on {field} needs a non-empty list of names")
            return Predicate(field=field, op="in", value=[_text(v) for v in value])
        raise InvalidPredicate(f"op {op!r} not allowed on {field}; use has, not_has or in")
    if op != "==":
        raise InvalidPredicate(f"op {op!r} not allowed on {field}; use ==")
    if kind == "sex":
        sex = str(value).lower()
        if sex not in ("female", "male"):
            raise InvalidPredicate(f"sex must be female or male, got {value!r}")
        return Predicate(field=field, op="==", value=sex)
    # bool: Predicate.value has no bool, so booleans travel as "true" / "false".
    flag = str(value).lower()
    if flag not in ("true", "false"):
        raise InvalidPredicate(f"{field} must be true or false, got {value!r}")
    return Predicate(field=field, op="==", value=flag)


def describe_vocabulary() -> str:
    """The field list as it appears in the compile prompt."""

    def names(kind: FieldKind) -> str:
        return ", ".join(f"`{f}`" for f, k in FIELD_KINDS.items() if k == kind and f not in _KEYED)

    numeric_ops = ", ".join(NUMERIC_OPS)
    lines = [
        f"- {names('numeric')} (years): {numeric_ops} with a number",
        f'- {names("sex")}: == with "female" or "male"',
        f'- {names("bool")}: == with "true" or "false"',
        f"- {names('list')}: `has` / `not_has` with one lowercase name, or `in` with a list"
        " of names (any of them)",
    ]
    for head, units in _KEYED.items():
        keys = ", ".join(f"`{head}.{k}` ({u})" for k, u in units.items())
        lines.append(f"- {keys}: {numeric_ops} with a number in that unit")
    return "\n".join(lines)
