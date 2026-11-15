"""Patient parser, note path: free-text note -> PatientFacts (SPEC.md pipeline 1).

    facts = await parse_patient(recorder, note, model_factory=anthropic_parse_model)

Haiku returns a `DraftPatient` via `with_structured_output(..., method="json_schema")` (a JSON
text answer, not a forced tool call): the PatientFacts vocabulary, but
with a required verbatim `source_span` on every fact, scalars included. Code then checks each
span against the note (case- and whitespace-insensitive) and builds the frozen `PatientFacts`:

- A fact whose span is not in the note is dropped (a scalar becomes None) and a `guardrail`
  event records it. Unverifiable facts never reach the rule engine.
- A verified span is rewritten to the note's own text, so later quote checks match exactly.
- A known lab or vital in a missing or non-canonical unit is dropped the same way (rules
  compare raw numbers).
- Nothing is inferred: a fact the note doesn't state (e.g. pregnant for a man) stays None.
- PatientFacts has no span field for age / sex / pregnant / smoker / location, so their
  verified spans are kept in the trace output only.

The FHIR path is deterministic and lives in `sources/synthea.py` (`parse_bundle`).
"""

import datetime as dt
import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from app.config import get_settings
from app.pipeline.predicate_fields import LAB_UNITS, VITAL_UNITS
from app.prompts import load_prompt
from app.schemas import Fact, PatientFacts
from app.trace.recorder import TraceRecorder

PROMPT_NAME = "parse_patient"

ModelFactory = Callable[[], BaseChatModel]

# --------------------------------------------------------------------------------------------
# LLM output (internal contract; PatientFacts is built from it in code)
# --------------------------------------------------------------------------------------------


class Spanned(BaseModel):
    source_span: str = Field(
        description="Verbatim, contiguous text copied from the note that states this fact"
    )


class DraftAge(Spanned):
    value: int = Field(description="Age in whole years")


class DraftSex(Spanned):
    value: Literal["female", "male"]


class DraftFlag(Spanned):
    value: bool


class DraftNamed(Spanned):
    value: str = Field(description="Short lowercase name, abbreviations spelled out")


class DraftMeasurement(Spanned):
    name: str = Field(description="Canonical key, e.g. hba1c, egfr, sbp, bmi")
    value: float
    unit: str | None = Field(default=None, description="The canonical unit for this key")
    date: dt.date | None = Field(default=None, description="Measurement date, if stated")


# HACK(demo): lat/lon are the model's guess at the city centre; no geocoder. The span check
# only proves the place is in the note, not that the coordinates are right.
class DraftLocation(Spanned):
    place: str = Field(description="Where the patient lives, as written in the note")
    lat: float = Field(description="Approximate latitude of the place")
    lon: float = Field(description="Approximate longitude of the place")


class DraftPatient(BaseModel):
    """Every fact the note states about the patient, each with its verbatim source span."""

    age: DraftAge | None = None
    sex: DraftSex | None = None
    conditions: list[DraftNamed] = Field(default_factory=list)
    labs: list[DraftMeasurement] = Field(default_factory=list)
    vitals: list[DraftMeasurement] = Field(default_factory=list)
    meds: list[DraftNamed] = Field(default_factory=list)
    pregnant: DraftFlag | None = None
    smoker: DraftFlag | None = None
    location: DraftLocation | None = None

    # Haiku sometimes answers an unmentioned list with null or the string "null" instead of [].
    @field_validator("conditions", "labs", "vitals", "meds", mode="before")
    @classmethod
    def _null_list_is_empty(cls, v: Any) -> Any:
        return [] if v is None or v == "null" else v


# --------------------------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------------------------


class ParseModelUnavailable(RuntimeError):
    """No parse model can be built (no API key)."""


class ParseFailed(RuntimeError):
    """The parse model's answer could not be parsed into DraftPatient."""


def anthropic_parse_model(api_key: str | None = None) -> BaseChatModel:
    """The real parse model (Haiku, `MODEL_PARSE`). `api_key` overrides the settings' key (the
    eval's `--offline` passes a placeholder: the key is not part of the LLM cache key)."""
    settings = get_settings()
    api_key = api_key or settings.anthropic_api_key
    if not api_key:
        raise ParseModelUnavailable("ANTHROPIC_API_KEY is not set; can't parse the patient note")
    return ChatAnthropic(
        model=settings.model_parse,
        api_key=SecretStr(api_key),
        max_tokens=4000,
    )


# --------------------------------------------------------------------------------------------
# Span verification and assembly
# --------------------------------------------------------------------------------------------


def find_span(span: str, note: str) -> str | None:
    """The note's own text for `span` (case- and whitespace-insensitive), or None.

    A span that starts or ends on a word character must start or end on a word boundary, so
    "M" doesn't match inside "metformin".
    """
    tokens = span.split()
    if not tokens:
        return None
    pattern = r"\s+".join(map(re.escape, tokens))
    if re.match(r"\w", tokens[0]):
        pattern = r"(?<!\w)" + pattern
    if re.search(r"\w$", tokens[-1]):
        pattern += r"(?!\w)"
    m = re.search(pattern, note, re.IGNORECASE)
    return m.group(0) if m else None


def _norm_unit(unit: str) -> str:
    return unit.replace("²", "2").replace(" ", "").lower()


class _Assembler:
    """Checks one draft against the note, recording a guardrail event per dropped fact."""

    def __init__(self, note: str, rec: TraceRecorder) -> None:
        self.note = note
        self.rec = rec
        self.dropped: list[str] = []

    def _drop(
        self, check: Literal["span", "unit", "range"], path: str, fact: BaseModel, error: str
    ) -> None:
        self.dropped.append(path)
        self.rec.event(
            f"{check}:{path}",
            "guardrail",
            status="failed",
            input={"path": path, "fact": fact.model_dump(mode="json")},
            output={"error": error, "action": "fact dropped"},
            note=f"{path}: {error}; dropped",
        )

    def verify(self, path: str, fact: Spanned) -> str | None:
        found = find_span(fact.source_span, self.note)
        if found is None:
            self._drop("span", path, fact, "source_span not found in the note")
        return found

    def named(self, head: str, drafts: list[DraftNamed]) -> list[Fact]:
        out: list[Fact] = []
        for i, d in enumerate(drafts):
            span = self.verify(f"{head}[{i}]", d)
            if span is not None:
                out.append(Fact(value=d.value.strip().lower(), source_span=span))
        return out

    def measurements(
        self, head: str, drafts: list[DraftMeasurement], units: dict[str, str]
    ) -> dict[str, Fact]:
        out: dict[str, Fact] = {}
        for d in drafts:
            key = d.name.strip().lower()
            path = f"{head}.{key}"
            canonical = units.get(key)
            if canonical is not None and (
                d.unit is None or _norm_unit(d.unit) != _norm_unit(canonical)
            ):
                self._drop("unit", path, d, f"unit {d.unit!r} is not the canonical {canonical!r}")
                continue
            span = self.verify(path, d)
            if span is None:
                continue
            fact = Fact(value=d.value, unit=canonical or d.unit, date=d.date, source_span=span)
            previous = out.get(key)
            # Several readings: keep the latest dated one, else the first.
            if previous is None or (d.date and (previous.date is None or d.date > previous.date)):
                out[key] = fact
        return out

    def build(self, draft: DraftPatient) -> tuple[PatientFacts, dict[str, str]]:
        """PatientFacts plus the verified spans of the scalar facts (for the trace)."""
        spans: dict[str, str] = {}

        def kept(path: str, d: Spanned | None) -> bool:
            """True when the scalar was extracted and its span verified."""
            span = self.verify(path, d) if d is not None else None
            if span is not None:
                spans[path] = span
            return span is not None

        age = draft.age.value if draft.age and kept("age", draft.age) else None
        sex = draft.sex.value if draft.sex and kept("sex", draft.sex) else None
        pregnant = (
            draft.pregnant.value if draft.pregnant and kept("pregnant", draft.pregnant) else None
        )
        smoker = draft.smoker.value if draft.smoker and kept("smoker", draft.smoker) else None

        lat = lon = place = None
        loc = draft.location
        if loc is not None:
            if not (-90 <= loc.lat <= 90 and -180 <= loc.lon <= 180):
                self._drop("range", "location", loc, "coordinates out of range")
            elif kept("location", loc):
                lat, lon, place = loc.lat, loc.lon, loc.place

        facts = PatientFacts(
            age=age,
            sex=sex,
            conditions=self.named("conditions", draft.conditions),
            labs=self.measurements("labs", draft.labs, LAB_UNITS),
            vitals=self.measurements("vitals", draft.vitals, VITAL_UNITS),
            meds=self.named("meds", draft.meds),
            pregnant=pregnant,
            smoker=smoker,
            lat=lat,
            lon=lon,
            place=place,
        )
        return facts, spans


def fact_count(facts: PatientFacts) -> int:
    scalars = (facts.age, facts.sex, facts.pregnant, facts.smoker, facts.lat)
    lists = len(facts.conditions) + len(facts.labs) + len(facts.vitals) + len(facts.meds)
    return lists + sum(v is not None for v in scalars)


def _describe_units() -> str:
    labs = ", ".join(f"`{k}` ({u})" for k, u in LAB_UNITS.items())
    vitals = ", ".join(f"`{k}` ({u})" for k, u in VITAL_UNITS.items())
    return f"  - labs: {labs}\n  - vitals: {vitals}"


# --------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------


async def parse_patient(
    rec: TraceRecorder,
    note: str,
    *,
    model_factory: ModelFactory = anthropic_parse_model,
) -> PatientFacts:
    """Parse one free-text note into PatientFacts (one traced LLM call + span guardrails)."""
    prompt = load_prompt(PROMPT_NAME)
    messages = [
        SystemMessage(prompt.render_system(units=_describe_units())),
        HumanMessage(prompt.render_user(note=note.strip())),
    ]
    async with rec.step(
        "parse_patient",
        "step",
        {"note_chars": len(note), "prompt": prompt.name, "prompt_version": prompt.version},
    ) as s:
        model = model_factory()
        runnable = model.with_structured_output(DraftPatient, method="json_schema")
        try:
            result: Any = await runnable.ainvoke(
                messages,
                config={
                    "callbacks": [rec.langchain_handler()],
                    "metadata": {"parent_id": s.id, "prompt_version": prompt.version},
                },
            )
        except (OutputParserException, ValidationError) as exc:
            raise ParseFailed(f"malformed parse output: {exc}") from exc
        if not isinstance(result, DraftPatient):
            raise ParseFailed(f"parse model returned {type(result).__name__}")

        assembler = _Assembler(note, rec)
        facts, spans = assembler.build(result)
        count = fact_count(facts)
        s.output = {
            "facts": count,
            "dropped": assembler.dropped,
            "scalar_spans": spans,
            "patient": facts.model_dump(mode="json"),
        }
        s.note = f"Parsed {len(note)} chars into {count} facts" + (
            f", dropped {len(assembler.dropped)} unverified" if assembler.dropped else ""
        )
    return facts
