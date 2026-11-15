"""LLM judge for criteria with no predicate (SPEC.md pipeline 4).

    semaphore = new_judge_semaphore()          # one per match run, shared by every trial
    verdicts = await judge_criteria(rec, items, facts, note, semaphore=semaphore)

    judge = llm_judge(model, trial_text=..., note=note, semaphore=semaphore)  # an evaluate.Judge

Each item is one `needs_judgment` criterion with its trial's (cleaned) eligibility text. The
judge model answers through `with_structured_output(JudgeOutput, method="json_schema")` (a JSON
text answer, not a forced tool call); `verify.verify_verdict` then
checks both quotes against their sources and downgrades unverifiable verdicts to `unknown`.

Failure handling, per criterion, never failing the batch:
- malformed output (parser/validation error, e.g. prose or invalid JSON) gets one retry, with
  the prompt's `## retry` turn naming the error appended; a second failure gives `unknown` plus
  an `error` event `judge:<nct>:<id>:malformed`.
- with no API key, `judge_criteria` raises `JudgeModelUnavailable` before any call; the caller
  decides whether that fails the run.
- any other model error (network, API) gives `unknown` plus an `error` event
  `judge:<nct>:<id>:error`, no retry (ChatAnthropic already retries transient API errors).

Trace: a `judge:<nct>:<id>` step per criterion (the verdict's `trace_event_id`) > one `llm` event
per attempt (prompt messages + raw output, via the LangChain callback) > a `verify:<nct>:<id>`
guardrail event, or the error event.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.config import get_settings
from app.pipeline.evaluate import Judge
from app.pipeline.verify import render_facts, verify_verdict
from app.prompts import Prompt, load_prompt
from app.schemas import Criterion, PatientFacts, Verdict
from app.trace.recorder import Step, TraceRecorder, describe_error

PROMPT_NAME = "judge"

# SPEC.md: asyncio.Semaphore(8) across trials and criteria.
JUDGE_CONCURRENCY = 8
MAX_ATTEMPTS = 2  # the first call plus one retry on malformed output

ModelFactory = Callable[[], BaseChatModel]


class JudgeOutput(BaseModel):
    """Your verdict on one eligibility criterion for this patient."""

    outcome: Literal["pass", "fail", "unknown"] = Field(
        description="pass = fine on this criterion, fail = disqualified, unknown = can't tell"
    )
    criterion_quote: str = Field(description="Verbatim span of the trial's eligibility text")
    patient_evidence: str | None = Field(
        description="Verbatim span of the patient note or one patient-facts line; null only "
        "for unknown"
    )
    rationale: str = Field(description="One or two sentences: requirement, record, outcome")


@dataclass(frozen=True)
class JudgeItem:
    nct_id: str
    criterion: Criterion
    trial_text: str  # the cleaned eligibility text (compile_criteria.clean_eligibility_text)


class JudgeModelUnavailable(RuntimeError):
    """No judge model can be built (no API key)."""


class _Malformed(Exception):
    pass


def model_id(model: BaseChatModel) -> str | None:
    """The model id a LangChain chat model will call (`model` on ChatAnthropic)."""
    name = getattr(model, "model", None) or getattr(model, "model_name", None)
    return str(name) if name else None


def new_judge_semaphore() -> asyncio.Semaphore:
    """The concurrency bound for judge calls. Make one per match run and pass the same one to
    every `judge_criteria` call in that run, so the bound holds across trials."""
    return asyncio.Semaphore(JUDGE_CONCURRENCY)


def anthropic_judge_model() -> BaseChatModel:
    """The real judge model (Sonnet, from settings)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise JudgeModelUnavailable("ANTHROPIC_API_KEY is not set; criteria can't be judged")
    return ChatAnthropic(
        model=settings.model_judge,
        api_key=SecretStr(settings.anthropic_api_key),
        max_tokens=2000,
    )


def _messages(
    prompt: Prompt, item: JudgeItem, facts: PatientFacts, note: str | None
) -> list[BaseMessage]:
    return [
        SystemMessage(prompt.render_system()),
        HumanMessage(
            prompt.render_user(
                nct_id=item.nct_id,
                trial_text=item.trial_text,
                criterion_type=item.criterion.type,
                criterion_id=item.criterion.id,
                criterion_text=item.criterion.text,
                patient_facts="\n".join(render_facts(facts)) or "(none)",
                patient_note=note or "(no note: the facts come from a structured record)",
            )
        ),
    ]


async def _ask(
    model: BaseChatModel,
    messages: list[BaseMessage],
    rec: TraceRecorder,
    step: Step,
    prompt: Prompt,
) -> JudgeOutput:
    """One judge call. Raises `_Malformed` when the answer isn't a valid `JudgeOutput`."""
    try:
        result = await model.with_structured_output(JudgeOutput, method="json_schema").ainvoke(
            messages,
            config={
                "callbacks": [rec.langchain_handler()],
                "metadata": {"parent_id": step.id, "prompt_version": prompt.version},
            },
        )
    except (OutputParserException, ValidationError) as exc:
        raise _Malformed(describe_error(exc)) from exc
    if not isinstance(result, JudgeOutput):
        # Narrows the type: the parser returns the schema or raises (prose, bad JSON) above
        raise _Malformed(f"no JudgeOutput (got {type(result).__name__})")
    return result


def _give_up(
    rec: TraceRecorder, item: JudgeItem, step: Step, kind: str, output: dict[str, Any], why: str
) -> Verdict:
    """Mark the judge step failed, emit `judge:<nct>:<id>:<kind>` (an `error` event) and return
    an `unknown` verdict. `verified` is true: the verdict quotes only the criterion text and
    claims no patient evidence, so there is nothing unverified to badge."""
    label = f"{item.nct_id}:{item.criterion.id}"
    step.status = "failed"
    step.output = {"outcome": "unknown", **output}
    rec.event(
        f"judge:{label}:{kind}",
        "error",
        status="failed",
        input={"criterion_id": item.criterion.id},
        output={**output, "action": "outcome=unknown"},
        note=f"{label}: {why}; marked unknown",
    )
    return Verdict(
        criterion_id=item.criterion.id,
        outcome="unknown",
        method="llm",
        criterion_quote=item.criterion.text,
        patient_evidence=None,
        rationale=f"No judgment: {why}.",
        verified=True,
        trace_event_id=step.id,
    )


async def judge_criterion(
    rec: TraceRecorder,
    item: JudgeItem,
    facts: PatientFacts,
    note: str | None,
    *,
    model: BaseChatModel,
) -> Verdict:
    """Judge one criterion: model call (+ one retry if malformed), then quote verification."""
    prompt = load_prompt(PROMPT_NAME)
    label = f"{item.nct_id}:{item.criterion.id}"
    async with rec.step(
        f"judge:{label}",
        "step",
        {
            "nct": item.nct_id,
            "criterion_id": item.criterion.id,
            "criterion_type": item.criterion.type,
            "criterion_text": item.criterion.text,
            "prompt": prompt.name,
            "prompt_version": prompt.version,
        },
        model=model_id(model),
    ) as s:
        messages = _messages(prompt, item, facts, note)
        problems: list[str] = []
        answer: JudgeOutput | None = None
        try:
            while answer is None and len(problems) < MAX_ATTEMPTS:
                if problems:  # the retry says what was wrong with the last answer
                    messages = [*messages, HumanMessage(prompt.render_retry(error=problems[-1]))]
                try:
                    answer = await _ask(model, messages, rec, s, prompt)
                except _Malformed as exc:
                    problems.append(str(exc))
        except Exception as exc:  # model/API failure: one criterion, not the whole run
            error = describe_error(exc)
            return _give_up(rec, item, s, "error", {"error": error}, f"judge call failed ({error})")
        if answer is None:
            return _give_up(
                rec,
                item,
                s,
                "malformed",
                {"attempts": len(problems), "errors": problems},
                f"malformed judge output {len(problems)} times",
            )

        draft = Verdict(
            criterion_id=item.criterion.id,
            outcome=answer.outcome,
            method="llm",
            criterion_quote=answer.criterion_quote,
            patient_evidence=answer.patient_evidence,
            rationale=answer.rationale,
            verified=False,  # set by verify_verdict
            trace_event_id=s.id,
        )
        verdict = verify_verdict(
            rec, draft, label=label, trial_text=item.trial_text, note=note, facts=facts
        )
        s.output = {
            "outcome": verdict.outcome,
            "judge_outcome": answer.outcome,
            "verified": verdict.verified,
            "attempts": len(problems) + 1,
        }
        if problems:  # validation errors of the attempts the retry recovered from
            s.output["errors"] = problems
        s.note = f"{label}: {verdict.outcome}" + ("" if verdict.verified else " (unverified)")
        return verdict


async def judge_criteria(
    rec: TraceRecorder,
    items: Sequence[JudgeItem],
    facts: PatientFacts,
    note: str | None,
    *,
    semaphore: asyncio.Semaphore,
    model_factory: ModelFactory = anthropic_judge_model,
) -> list[Verdict]:
    """Judge every item concurrently, at most `semaphore`'s worth of calls at once.

    Pass the run's one `new_judge_semaphore()` to every call so the bound spans trials.
    Returns verdicts in input order. Raises `JudgeModelUnavailable` (before any call) when
    there is no API key.
    """
    if not items:
        return []
    model = model_factory()

    async def one(item: JudgeItem) -> Verdict:
        async with semaphore:
            return await judge_criterion(rec, item, facts, note, model=model)

    return list(await asyncio.gather(*(one(item) for item in items)))


def llm_judge(
    model: BaseChatModel, *, trial_text: str, note: str | None, semaphore: asyncio.Semaphore
) -> Judge:
    """An `evaluate.Judge` for one trial: judges each criterion it's handed against that trial's
    cleaned eligibility text, holding a slot of the run's shared `semaphore` per call."""

    async def judge(
        nct_id: str, criterion: Criterion, facts: PatientFacts, rec: TraceRecorder
    ) -> Verdict:
        async with semaphore:
            item = JudgeItem(nct_id, criterion, trial_text)
            return await judge_criterion(rec, item, facts, note, model=model)

    return judge
