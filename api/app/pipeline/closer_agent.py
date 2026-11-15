"""Closer agent (SPEC.md pipeline 5): the only open-ended agent.

    find_trial_match(run_id, nct)                  # the route's 404/409 check, before any LLM
    result = await run_closer(rec, req, model=model)   # {"closer": CloserOutput, ...}

A LangGraph `create_react_agent` over Sonnet with four read-only tools (`closer_tools()`):
`get_match_result`, `get_unknown_criteria`, `get_trial_contacts`, `get_patient_facts`. They read
the finished match run and the trial cache in SQLite, never the network. The agent ends with a
structured `CloserOutput` (follow-ups, coordinator email, English + Spanish patient summary).

Trace: a `closer_agent` step > for each agent turn an `llm` event (prompt + raw output, via the
LangChain callback) and a `thought` event (the turn's text and the tool calls it asked for) >
one `tool` event per call (args, then the result, streamed as it happens) > the structured
answer's `llm` event > a `closer:followup_coverage` guardrail (one follow-up per unknown).

`recursion_limit=8` graph steps. LangGraph's prebuilt agent doesn't raise when it runs out: it
swaps the last turn for a fixed "need more steps" message. Either way the run fails with a
`closer_agent:recursion_limit` error event and no structured answer is requested.
"""

import warnings
from contextlib import aclosing
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tools import BaseTool, tool
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.warnings import LangGraphDeprecatedSinceV10
from pydantic import SecretStr

from app.config import get_settings
from app.pipeline import criteria_cache
from app.pipeline.judge import model_id
from app.pipeline.trial_search import sites_by_distance
from app.prompts import Prompt, load_prompt
from app.schemas import CloserOutput, CloserRequest
from app.sources import ctgov
from app.trace import store
from app.trace.recorder import Step, TraceRecorder

PROMPT_NAME = "closer"
RECURSION_LIMIT = 8  # SPEC.md
NEAREST_SITES = 3
# What `create_react_agent` puts in place of a turn when too few steps remain (langgraph
# prebuilt `chat_agent_executor`). Seeing it means the agent hit the recursion limit.
OUT_OF_STEPS = "Sorry, need more steps to process this request."
# Verdict fields only the UI needs; kept out of what the model reads.
_VERDICT_INTERNALS = ("trace_event_id", "verified")


class CloserToolError(LookupError):
    """A tool can't answer (unknown run, trial not in the run, trial not cached)."""


class MatchRunNotFinished(CloserToolError):
    """The match run exists but has no result yet."""


class CloserModelUnavailable(RuntimeError):
    """No closer model can be built (no API key)."""


class CloserRecursionLimit(RuntimeError):
    """The agent used up `RECURSION_LIMIT` graph steps without an answer."""


# --------------------------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------------------------


def _match_run(run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(request, result) of a finished match run."""
    run = store.get_run(run_id)
    if run is None or run.kind != "match":
        raise CloserToolError(f"no match run {run_id}")
    if run.status != "done" or not run.result:
        raise MatchRunNotFinished(f"match run {run_id} has not finished ({run.status})")
    return run.request or {}, run.result


def find_trial_match(run_id: str, nct: str) -> dict[str, Any]:
    """The stored `TrialMatch` JSON of `nct` in match run `run_id`. Raises `CloserToolError`."""
    _, result = _match_run(run_id)
    nct = nct.strip().upper()
    for match in result.get("matches", []):
        if match["nct_id"] == nct:
            return dict(match)
    raise CloserToolError(f"{nct} is not among the trials of match run {run_id}")


def unknown_criteria(run_id: str, nct: str) -> list[dict[str, Any]]:
    """The run's `unknown` verdicts for `nct`, joined with the compiled criterion text."""
    match = find_trial_match(run_id, nct)
    compiled = {c.id: c for c in criteria_cache.latest(match["nct_id"])}
    criteria = []
    for verdict in match["verdicts"]:
        if verdict["outcome"] != "unknown":
            continue
        criterion = compiled.get(verdict["criterion_id"])
        criteria.append(
            {
                "criterion_id": verdict["criterion_id"],
                "type": criterion.type if criterion else None,
                "category": criterion.category if criterion else None,
                "text": criterion.text if criterion else verdict["criterion_quote"],
                "rationale": verdict["rationale"],
            }
        )
    return criteria


# The tools are `async` on purpose: LangChain runs sync tools in a thread pool, and their trace
# callbacks would then emit off the event loop, out of seq order (the SSE stream drops those).


@tool
async def get_match_result(run_id: str, nct: str) -> dict[str, Any]:
    """How the patient of match run `run_id` matched trial `nct`: title, phase, distance, tier
    (likely / needs_info / ineligible), outcome counts, and one verdict per eligibility
    criterion (outcome pass / fail / unknown, the trial quote, patient evidence, rationale)."""
    match = find_trial_match(run_id, nct)
    match["verdicts"] = [
        {k: v for k, v in verdict.items() if k not in _VERDICT_INTERNALS}
        for verdict in match["verdicts"]
    ]
    return match


@tool
async def get_unknown_criteria(run_id: str, nct: str) -> dict[str, Any]:
    """The eligibility criteria of trial `nct` whose outcome is `unknown` for the patient of
    match run `run_id` (the data was missing): id, inclusion/exclusion, category, the criterion
    text from the trial, and why the matcher could not decide. Each needs a follow-up."""
    return {"nct_id": nct.strip().upper(), "criteria": unknown_criteria(run_id, nct)}


def _contact(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw[k] for k in ("name", "role", "phone", "email") if raw.get(k)}


@tool
async def get_trial_contacts(nct: str) -> dict[str, Any]:
    """Who to contact about trial `nct`: its central contacts, and the recruiting sites nearest
    Sacramento with their own contacts and distance in miles."""
    nct = nct.strip().upper()
    study = ctgov.cached_study(nct)
    if study is None:
        raise CloserToolError(f"{nct} is not in the trial cache")
    proto = study["protocolSection"]
    module = proto.get("contactsLocationsModule", {})
    nearest = sites_by_distance(study, ctgov.SACRAMENTO)[:NEAREST_SITES]
    return {
        "nct_id": nct,
        "title": proto.get("identificationModule", {}).get("briefTitle"),
        "central_contacts": [_contact(c) for c in module.get("centralContacts") or []],
        "nearest_sites": [
            {
                "facility": loc.get("facility"),
                "city": loc.get("city"),
                "state": loc.get("state"),
                "status": loc.get("status"),
                "distance_mi": round(miles, 1),
                "contacts": [_contact(c) for c in loc.get("contacts") or []],
            }
            for miles, loc in nearest
        ],
    }


@tool
async def get_patient_facts(run_id: str) -> dict[str, Any]:
    """The patient of match run `run_id`: the structured facts (age, sex, conditions, labs,
    vitals, meds, pregnancy, smoking) and the original clinic note, if the run started from
    one."""
    request, result = _match_run(run_id)
    return {"patient": result.get("patient"), "note": request.get("note")}


def closer_tools() -> list[BaseTool]:
    return [get_match_result, get_unknown_criteria, get_trial_contacts, get_patient_facts]


# --------------------------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------------------------


FINAL_ANSWER_TURN = "Give your final answer now, in the required format."


def end_on_user_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    """`messages`, plus a user turn asking for the answer when the last one is the agent's own:
    Anthropic's output format refuses a request that ends on an assistant message (a prefill)."""
    if messages and isinstance(messages[-1], AIMessage):
        return [*messages, HumanMessage(FINAL_ANSWER_TURN)]
    return messages


class _JsonSchemaChatAnthropic(ChatAnthropic):
    """ChatAnthropic whose structured output defaults to `json_schema`, like every other LLM step,
    and always ends on a user turn. `create_react_agent` asks for the final answer with no method
    (langchain-anthropic's default, forced tool calling, is refused by newer Sonnet models) and
    with the agent's last AI turn at the end of the conversation."""

    def with_structured_output(
        self, schema: Any, *, method: Any = "json_schema", **kwargs: Any
    ) -> Any:
        structured = super().with_structured_output(schema, method=method, **kwargs)
        return RunnableLambda(end_on_user_turn) | structured


def anthropic_closer_model() -> BaseChatModel:
    """The real closer model (Sonnet, from settings)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise CloserModelUnavailable("ANTHROPIC_API_KEY is not set; the closer agent can't run")
    return _JsonSchemaChatAnthropic(
        model=settings.model_closer,
        api_key=SecretStr(settings.anthropic_api_key),
        max_tokens=16000,  # one follow-up per unknown criterion; ROC-101 has 67
    )


def _agent(model: BaseChatModel, prompt: Prompt) -> Any:
    system = prompt.render_system()
    with warnings.catch_warnings():
        # SPEC.md names `create_react_agent`; LangGraph 1.x points at `langchain.agents`.
        warnings.simplefilter("ignore", LangGraphDeprecatedSinceV10)
        return create_react_agent(
            model,
            # Tool errors go back to the model as a message (and a failed `tool` event).
            ToolNode(closer_tools(), handle_tool_errors=True),
            prompt=system,
            response_format=(system, CloserOutput),
        )


def _thought(rec: TraceRecorder, message: AIMessage) -> None:
    """One agent turn as a trace event: its text and the tool calls it asked for."""
    names = [c["name"] for c in message.tool_calls]
    calls = [{"name": c["name"], "args": c["args"]} for c in message.tool_calls]
    text = message.text.strip()
    rec.event(
        "thought",
        "step",
        output={"text": text, "tool_calls": calls},
        note=text or ("calls " + ", ".join(names)),
    )


def _record_out_of_steps(rec: TraceRecorder, step: Step, detail: str) -> CloserRecursionLimit:
    rec.event(
        "closer_agent:recursion_limit",
        "error",
        status="failed",
        output={"recursion_limit": RECURSION_LIMIT, "error": detail},
        note=f"agent stopped: recursion limit of {RECURSION_LIMIT} steps reached, no answer",
    )
    step.note = "recursion limit reached"
    return CloserRecursionLimit(f"no answer within recursion_limit={RECURSION_LIMIT}")


async def _drive(
    rec: TraceRecorder, step: Step, model: BaseChatModel, prompt: Prompt, req: CloserRequest
) -> CloserOutput:
    """Run the agent graph, emitting a `thought` per turn; return its structured answer."""
    config: RunnableConfig = {
        "callbacks": [rec.langchain_handler()],
        "metadata": {"parent_id": step.id, "prompt_version": prompt.version},
        "recursion_limit": RECURSION_LIMIT,
    }
    messages: list[BaseMessage] = [
        HumanMessage(prompt.render_user(run_id=req.run_id, nct_id=req.nct_id))
    ]
    answer: Any = None
    try:
        stream = _agent(model, prompt).astream(
            {"messages": messages}, config=config, stream_mode="updates"
        )
        async with aclosing(stream):
            async for update in stream:
                for node, delta in update.items():
                    if node == "agent":
                        for message in delta["messages"]:
                            if message.content == OUT_OF_STEPS:
                                # Stop before the graph asks for an answer it can't have.
                                raise _record_out_of_steps(rec, step, OUT_OF_STEPS)
                            _thought(rec, message)
                    elif node == "generate_structured_response":
                        answer = delta["structured_response"]
    except GraphRecursionError as exc:
        raise _record_out_of_steps(rec, step, str(exc)) from exc
    if not isinstance(answer, CloserOutput):
        raise ValueError(f"the agent returned no CloserOutput (got {type(answer).__name__})")
    return answer


def _check_coverage(rec: TraceRecorder, req: CloserRequest, output: CloserOutput) -> None:
    """Guardrail: exactly the unknown criteria get follow-ups (none missing, none invented)."""
    expected = [c["criterion_id"] for c in unknown_criteria(req.run_id, req.nct_id)]
    covered = [f.criterion_id for f in output.followups]
    missing = [c for c in expected if c not in covered]
    extra = [c for c in covered if c not in expected]
    ok = not missing and not extra
    rec.event(
        "closer:followup_coverage",
        "guardrail",
        status="ok" if ok else "failed",
        input={"unknown_criteria": expected},
        output={"followups": covered, "missing": missing, "extra": extra},
        note=(
            f"a follow-up for each of {len(expected)} unknown criteria"
            if ok
            else f"follow-ups missing {missing or 'none'}, not unknown {extra or 'none'}"
        ),
    )


async def run_closer(
    rec: TraceRecorder, req: CloserRequest, *, model: BaseChatModel
) -> dict[str, Any]:
    """The whole closer run. Returns the run result stored on the run row (read back by
    `GET /api/runs/{run_id}`): `{"closer": CloserOutput, "source_run_id", "nct_id"}`.
    Raises `CloserRecursionLimit` when the agent runs out of steps."""
    prompt = load_prompt(PROMPT_NAME)
    step_input = {
        "run_id": req.run_id,
        "nct_id": req.nct_id,
        "prompt": prompt.name,
        "prompt_version": prompt.version,
        "recursion_limit": RECURSION_LIMIT,
    }
    async with rec.step("closer_agent", "run", step_input, model=model_id(model)) as s:
        output = await _drive(rec, s, model, prompt, req)
        _check_coverage(rec, req, output)
        s.output = output.model_dump(mode="json")
        s.note = (
            f"{len(output.followups)} follow-ups, email to "
            f"{output.coordinator_email.to or 'the study team'}, summary in English and Spanish"
        )
    return {"closer": s.output, "source_run_id": req.run_id, "nct_id": req.nct_id}
