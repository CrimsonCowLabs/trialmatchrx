"""Criteria compiler: a trial's eligibility module -> list[Criterion] (SPEC.md pipeline 3).

    criteria = await compile_study(study, recorder, model_factory=anthropic_compile_model)

`study` is a raw ClinicalTrials.gov v2 study dict; where it came from is the caller's business.
Age and sex are built in code from the structured fields. The free text goes to the compile
model once via `with_structured_output(CompiledCriteria)`; every predicate it writes is checked
against PatientFacts and downgraded to `needs_judgment` if invalid. Results are cached per
NCT id + eligibility hash + prompt version. Every step, LLM call and guardrail is traced.
"""

import re
from collections.abc import Callable
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.config import get_settings
from app.pipeline import criteria_cache
from app.pipeline.predicate_fields import InvalidPredicate, describe_vocabulary, validate_predicate
from app.pipeline.verify import normalize
from app.prompts import load_prompt
from app.schemas import Criterion, Predicate
from app.trace.recorder import TraceRecorder

PROMPT_NAME = "compile_criteria"

ModelFactory = Callable[[], BaseChatModel]

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


# --------------------------------------------------------------------------------------------
# LLM output (what the compile model returns; validated and numbered in code)
# --------------------------------------------------------------------------------------------

Category = Literal["demographic", "diagnosis", "lab", "medication", "history", "procedure", "other"]


class DraftPredicate(BaseModel):
    """Looser than `Predicate` on purpose: a bad op or value is a downgrade, not a parse error."""

    field: str = Field(description="PatientFacts path, e.g. labs.egfr, conditions, age")
    op: str = Field(description=">=, <=, >, <, ==, in, has or not_has")
    value: float | str | list[str] | bool
    unit: str | None = Field(default=None, description="The canonical unit for the field")


class DraftCriterion(BaseModel):
    type: Literal["inclusion", "exclusion"]
    text: str = Field(description="Verbatim span copied from the eligibility text")
    category: Category
    predicate: DraftPredicate | None = Field(
        description="Null when the criterion can't be checked from the listed patient fields"
    )


class CompiledCriteria(BaseModel):
    """Every atomic eligibility criterion of the trial, in the order they appear."""

    criteria: list[DraftCriterion]


# --------------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------------

_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>^~|=])")


def clean_eligibility_text(text: str) -> str:
    """ClinicalTrials.gov stores criteria as markdown with escapes (`\\>`, `\\[`); drop them so
    the model quotes what a reader sees."""
    return _MD_ESCAPE.sub(r"\1", text).strip()


def predicate_count(criteria: list[Criterion]) -> int:
    return sum(c.predicate is not None for c in criteria)


def compile_rate(criteria: list[Criterion]) -> float | None:
    """Share of criteria with a predicate (SPEC.md target: ~60%)."""
    return predicate_count(criteria) / len(criteria) if criteria else None


class CompileModelUnavailable(RuntimeError):
    """No compile model can be built (no API key) and the cache missed."""


class CompileFailed(RuntimeError):
    """The compile model's answer could not be parsed into CompiledCriteria."""


def anthropic_compile_model() -> BaseChatModel:
    """The real compile model (Sonnet, from settings). Built only on a cache miss."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise CompileModelUnavailable(
            "ANTHROPIC_API_KEY is not set and this trial is not in the compile cache"
        )
    return ChatAnthropic(
        model=settings.model_compile,
        api_key=SecretStr(settings.anthropic_api_key),
        max_tokens=16000,
    )


# --------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------


def _finalize(
    drafts: list[DraftCriterion], source_text: str, rec: TraceRecorder
) -> list[Criterion]:
    """Number the drafts `inc-N` / `exc-N`, validate predicates, check quotes."""
    counters = {"inclusion": 0, "exclusion": 0}
    haystack = normalize(source_text)
    out: list[Criterion] = []
    for draft in drafts:
        counters[draft.type] += 1
        crit_id = f"{draft.type[:3]}-{counters[draft.type]}"
        predicate: Predicate | None = None
        if draft.predicate is not None:
            raw = draft.predicate.model_dump()
            try:
                predicate = validate_predicate(raw)
            except InvalidPredicate as exc:
                rec.event(
                    f"predicate:{crit_id}",
                    "guardrail",
                    status="failed",
                    input={"criterion_id": crit_id, "text": draft.text, "predicate": raw},
                    output={"error": str(exc), "action": "predicate=null, needs_judgment=true"},
                    note=f"{crit_id}: invalid predicate downgraded to needs_judgment",
                )
        if normalize(draft.text) not in haystack:
            rec.event(
                f"quote:{crit_id}",
                "guardrail",
                status="failed",
                input={"criterion_id": crit_id, "text": draft.text},
                output={"error": "criterion text is not a verbatim span of the trial text"},
                note=f"{crit_id}: quote not found in the eligibility text",
            )
        out.append(
            Criterion(
                id=crit_id,
                type=draft.type,
                text=draft.text,
                category=draft.category,
                predicate=predicate,
                needs_judgment=predicate is None,
            )
        )
    return out


async def _llm_split(
    nct_id: str, text: str, rec: TraceRecorder, model_factory: ModelFactory
) -> tuple[list[Criterion], str | None]:
    """The LLM part: returns the numbered, validated criteria and the model id that ran."""
    prompt = load_prompt(PROMPT_NAME)
    messages = [
        SystemMessage(prompt.render_system(vocabulary=describe_vocabulary())),
        HumanMessage(prompt.render_user(nct_id=nct_id, eligibility_text=text)),
    ]
    async with rec.step(
        "llm_split", "step", {"prompt": prompt.name, "prompt_version": prompt.version}
    ) as s:
        model = model_factory()
        model_id = getattr(model, "model", None) or getattr(model, "model_name", None)
        runnable = model.with_structured_output(CompiledCriteria)
        try:
            result = await runnable.ainvoke(
                messages,
                config={
                    "callbacks": [rec.langchain_handler()],
                    "metadata": {"parent_id": s.id, "prompt_version": prompt.version},
                },
            )
        except (OutputParserException, ValidationError) as exc:
            raise CompileFailed(f"{nct_id}: malformed compile output: {exc}") from exc
        if not isinstance(result, CompiledCriteria):
            # e.g. no tool call at all (max_tokens hit, or the model answered in prose)
            raise CompileFailed(f"{nct_id}: compile model returned {type(result).__name__}")
        criteria = _finalize(result.criteria, text, rec)
        s.output = {
            "criteria": len(criteria),
            "invalid_predicates": sum(
                d.predicate is not None and c.predicate is None
                for d, c in zip(result.criteria, criteria, strict=True)
            ),
        }
        return criteria, (str(model_id) if model_id else None)


async def compile_study(
    study: dict[str, Any],
    rec: TraceRecorder,
    *,
    model_factory: ModelFactory = anthropic_compile_model,
    force: bool = False,
) -> list[Criterion]:
    """Compile one raw ClinicalTrials.gov v2 study into its criteria (cached, traced)."""
    protocol = study.get("protocolSection", {})
    nct_id: str = protocol["identificationModule"]["nctId"]
    eligibility: dict[str, Any] = protocol.get("eligibilityModule", {})
    prompt = load_prompt(PROMPT_NAME)
    key = criteria_cache.eligibility_hash(eligibility)

    async with rec.step(
        "compile_criteria",
        "step",
        {"nct": nct_id, "criteria_hash": key, "prompt_version": prompt.version, "force": force},
    ) as top:
        lookup_input = {"nct": nct_id, "criteria_hash": key}
        async with rec.step("cache_lookup", "step", lookup_input) as lookup:
            if force:
                cached = None
                lookup.status = "skipped"
                lookup.note = "force: cache bypassed"
            else:
                cached = criteria_cache.get(nct_id, key, prompt.version)
                lookup.cache_hit = cached is not None
                lookup.note = "cache hit" if cached is not None else "cache miss"
            lookup.output = {"hit": cached is not None}

        if cached is not None:
            criteria = cached
            top.cache_hit = True
        else:
            async with rec.step(
                "structured_criteria",
                "rule",
                {k: eligibility.get(k) for k in ("minimumAge", "maximumAge", "sex")},
            ) as s:
                structured = structured_criteria(eligibility)
                s.output = {"criteria": [c.model_dump(mode="json") for c in structured]}

            text = clean_eligibility_text(eligibility.get("eligibilityCriteria") or "")
            llm_criteria, model_id = (
                await _llm_split(nct_id, text, rec, model_factory) if text else ([], None)
            )
            criteria = structured + llm_criteria
            criteria_cache.put(nct_id, key, prompt.version, model_id, criteria)

        rate = compile_rate(criteria)
        top.output = {
            "criteria": len(criteria),
            "with_predicate": predicate_count(criteria),
            "compile_rate": rate,
        }
        if rate is not None:
            top.note = f"{len(criteria)} criteria, compile rate {rate:.0%}"
    return criteria
