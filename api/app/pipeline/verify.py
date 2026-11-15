"""Quote verification guardrail (SPEC.md "Guardrail: quote verification").

    ok = quote_present(verdict.criterion_quote, [trial_text])

A quote is present in a source when, after lowercasing and collapsing whitespace, the best
matching window of the source scores a rapidfuzz `partial_ratio` of at least 90 AND every
number in the quote appears in that window.

Why `partial_ratio`, not `ratio`: the quote is a span of a much longer source, and `ratio`
compares whole strings, so a perfect 40-char quote from a 2,000-char note scores ~4.
`partial_ratio` scores the quote against its best-aligned window of the source, i.e. it is
substring matching that tolerates a typo or two. Two cases it gets wrong are guarded in code:
- it swaps its arguments when the quote is longer than the source, so a long invented quote
  around a short real fact would score 100. A quote longer than its source falls back to `ratio`.
- one changed digit in a short quote ("eGFR 148" vs "eGFR 48") still scores ~88; for clinical
  values that is a different fact, so numbers must match exactly.
"""

import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from app.schemas import Fact, PatientFacts, Verdict
from app.trace.recorder import TraceRecorder

MIN_RATIO = 90.0

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def normalize(text: str) -> str:
    """Lowercase and collapse every run of whitespace to one space."""
    return " ".join(text.lower().split())


def _token_window(source: str, start: int, end: int) -> str:
    """Widen [start, end) to whole whitespace-separated tokens, so numbers aren't clipped."""
    start = source.rfind(" ", 0, start) + 1
    stop = source.find(" ", end)
    return source[start : len(source) if stop == -1 else stop]


def quote_score(quote: str, source: str) -> float:
    """0-100: how well `quote` matches some span of `source` (numbers must match exactly)."""
    q, s = normalize(quote), normalize(source)
    if not q or not s:
        return 0.0
    if len(q) > len(s):
        window, score = s, fuzz.ratio(q, s)
    else:
        aligned = fuzz.partial_ratio_alignment(q, s)
        if aligned is None:
            return 0.0
        window, score = _token_window(s, aligned.dest_start, aligned.dest_end), aligned.score
    if not set(_NUMBER.findall(q)) <= set(_NUMBER.findall(window)):
        return 0.0
    return float(score)


def quote_present(quote: str, sources: Iterable[str]) -> bool:
    """True when `quote` is present (per the rules above) in at least one of `sources`."""
    return any(quote_score(quote, source) >= MIN_RATIO for source in sources)


# --------------------------------------------------------------------------------------------
# Patient facts as quotable text
# --------------------------------------------------------------------------------------------


def _value(value: str | float | bool) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 48.0 -> "48", as a note would write it
    return str(value)


def _fact_line(path: str, fact: Fact) -> str:
    unit = f" {fact.unit}" if fact.unit else ""
    when = f" ({fact.date.isoformat()})" if fact.date else ""
    return f"{path}: {_value(fact.value)}{unit}{when}"


def render_facts(facts: PatientFacts) -> list[str]:
    """One line per known fact, e.g. `labs.egfr: 48 mL/min/1.73m2 (2026-10-02)`.

    The judge prompt shows the facts in exactly this form and verification checks evidence
    against the same lines, so a fact with no note behind it (FHIR path) is still quotable.
    """
    lines: list[str] = []
    for name in ("age", "sex", "pregnant", "smoker"):
        value = getattr(facts, name)
        if value is not None:
            lines.append(f"{name}: {_value(value)}")
    lines += [_fact_line("conditions", f) for f in facts.conditions]
    lines += [_fact_line(f"labs.{key}", f) for key, f in facts.labs.items()]
    lines += [_fact_line(f"vitals.{key}", f) for key, f in facts.vitals.items()]
    lines += [_fact_line("meds", f) for f in facts.meds]
    return lines


def _fact_spans(facts: PatientFacts) -> list[str]:
    every = [*facts.conditions, *facts.labs.values(), *facts.vitals.values(), *facts.meds]
    return [f.source_span for f in every if f.source_span]


# --------------------------------------------------------------------------------------------
# The guardrail
# --------------------------------------------------------------------------------------------


def _failure(field: str, quote: str | None, reason: str) -> dict[str, str | None]:
    return {"field": field, "quote": quote, "reason": reason}


def verify_verdict(
    rec: TraceRecorder,
    verdict: Verdict,
    *,
    label: str,
    trial_text: str,
    note: str | None,
    facts: PatientFacts,
) -> Verdict:
    """Check the verdict's quotes; downgrade to `unknown` + `verified: false` if any fails.

    - `criterion_quote` must be present in `trial_text` (the cleaned eligibility text).
    - `patient_evidence` must be present in the note, a fact's source span, or a rendered fact
      line. It may be null only when the outcome is `unknown`: a pass or fail with no patient
      quote is unsupported.

    Emits one `guardrail` event, `verify:<label>`: `ok` when verified, `failed` with what
    failed when downgraded.
    """
    failed: list[dict[str, str | None]] = []
    if not quote_present(verdict.criterion_quote, [trial_text]):
        failed.append(
            _failure(
                "criterion_quote",
                verdict.criterion_quote,
                "not found in the trial's eligibility text",
            )
        )
    evidence = verdict.patient_evidence
    if evidence is None:
        if verdict.outcome != "unknown":
            failed.append(
                _failure("patient_evidence", None, f"missing, but the outcome is {verdict.outcome}")
            )
    elif not quote_present(evidence, [note or "", *_fact_spans(facts), *render_facts(facts)]):
        failed.append(
            _failure("patient_evidence", evidence, "not found in the patient note or facts")
        )

    check_input = {
        "criterion_id": verdict.criterion_id,
        "criterion_quote": verdict.criterion_quote,
        "patient_evidence": evidence,
        "min_ratio": MIN_RATIO,
    }
    if not failed:
        rec.event(
            f"verify:{label}",
            "guardrail",
            input=check_input,
            output={"verified": True},
            note=f"{label}: quotes verified",
        )
        return verdict.model_copy(update={"verified": True})

    fields = ", ".join(str(f["field"]) for f in failed)
    rec.event(
        f"verify:{label}",
        "guardrail",
        status="failed",
        input=check_input,
        output={
            "verified": False,
            "failed": failed,
            "original_outcome": verdict.outcome,
            "action": "outcome=unknown, verified=false",
        },
        note=f"{label}: unverified {fields}; {verdict.outcome} downgraded to unknown",
    )
    return verdict.model_copy(
        update={
            "outcome": "unknown",
            "verified": False,
            "rationale": f"Unverified quote ({fields}); the judge said {verdict.outcome}: "
            f"{verdict.rationale}",
        }
    )
