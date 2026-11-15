"""TraceRecorder: the one way pipeline code writes trace events.

    rec = TraceRecorder(run_id, bus)
    async with rec.step("compile_criteria", "step", {"nct": nct}) as s:
        s.output = {...}           # status becomes "ok" on exit, "failed" on exception
    rec.event("rule:inc-3", "rule", input=..., output=...)   # one-shot decision

LLM and tool calls are traced by passing `rec.langchain_handler()` as a LangChain callback.

A step is emitted twice under the same event id: `started` on enter, its final state on exit,
each with a new seq. Consumers upsert by `id`. Every emission is persisted to SQLite and then
published on the bus, synchronously, so seq order == storage order == publish order.
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from app.config import get_settings
from app.schemas import TraceEvent, TraceKind, TraceStatus
from app.trace import store
from app.trace.bus import EventBus


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def describe_error(exc: BaseException) -> str:
    """How errors read in trace output and run rows: `ValueError: boom`."""
    return f"{type(exc).__name__}: {exc}"


@dataclass
class Step:
    """Mutable handle yielded by `TraceRecorder.step`. Set fields inside the block."""

    id: str
    name: str
    kind: TraceKind
    parent_id: str | None
    input: dict[str, Any] | None
    started_at: dt.datetime
    output: dict[str, Any] | None = None
    note: str | None = None
    # Final status. Left as None the recorder uses "ok" (or "failed" on exception).
    status: TraceStatus | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    cache_hit: bool = False


class TraceRecorder:
    def __init__(
        self,
        run_id: str,
        bus: EventBus,
    ) -> None:
        self.run_id = run_id
        self._bus = bus
        self._seq = 0
        # Per-recorder so that concurrent runs never inherit each other's parents.
        self._current: ContextVar[str | None] = ContextVar(f"trace_parent_{run_id}", default=None)

    @property
    def current_step_id(self) -> str | None:
        """Id of the innermost open step in this task, used as the default parent."""
        return self._current.get()

    def emit(self, event: TraceEvent) -> TraceEvent:
        """Assign the next seq, persist, publish. Returns the stamped event."""
        self._seq += 1
        stamped = event.model_copy(update={"seq": self._seq, "run_id": self.run_id})
        store.save_event(stamped)
        self._bus.publish(stamped)
        return stamped

    def _build(self, step: Step, status: TraceStatus, ended_at: dt.datetime | None) -> TraceEvent:
        return TraceEvent(
            id=step.id,
            run_id=self.run_id,
            parent_id=step.parent_id,
            seq=0,  # stamped by emit()
            kind=step.kind,
            name=step.name,
            status=status,
            started_at=step.started_at,
            ended_at=ended_at,
            input=step.input,
            output=step.output,
            model=step.model,
            tokens_in=step.tokens_in,
            tokens_out=step.tokens_out,
            cost_usd=step.cost_usd,
            cache_hit=step.cache_hit,
            note=step.note,
        )

    def open_step(
        self,
        name: str,
        kind: TraceKind = "step",
        input: dict[str, Any] | None = None,
        *,
        parent_id: str | None = None,
        note: str | None = None,
        model: str | None = None,
    ) -> Step:
        """Emit a `started` event and return its handle. Pair with `close_step`.

        Prefer `step()`; this pair exists for callback-style code (LangChain handlers).
        """
        step = Step(
            id=str(uuid.uuid4()),
            name=name,
            kind=kind,
            parent_id=parent_id if parent_id is not None else self.current_step_id,
            input=input,
            started_at=_now(),
            note=note,
            model=model,
        )
        self.emit(self._build(step, "started", None))
        return step

    def close_step(self, step: Step, status: TraceStatus | None = None) -> TraceEvent:
        return self.emit(self._build(step, status or step.status or "ok", _now()))

    @asynccontextmanager
    async def step(
        self,
        name: str,
        kind: TraceKind = "step",
        input: dict[str, Any] | None = None,
        *,
        parent_id: str | None = None,
        note: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[Step]:
        step = self.open_step(name, kind, input, parent_id=parent_id, note=note, model=model)
        token = self._current.set(step.id)
        try:
            yield step
        except BaseException as exc:
            if step.output is None:
                step.output = {"error": describe_error(exc)}
            self.close_step(step, "failed")
            raise
        else:
            self.close_step(step)
        finally:
            self._current.reset(token)

    def langchain_handler(self) -> "TraceCallbackHandler":
        """Callback for `config={"callbacks": [rec.langchain_handler()], "metadata": {...}}`."""
        return TraceCallbackHandler(self)

    def event(
        self,
        name: str,
        kind: TraceKind,
        *,
        status: TraceStatus = "ok",
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        note: str | None = None,
        parent_id: str | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        cache_hit: bool = False,
    ) -> TraceEvent:
        """Emit a one-shot, already-finished event (rule result, guardrail check, ...)."""
        now = _now()
        return self.emit(
            TraceEvent(
                id=str(uuid.uuid4()),
                run_id=self.run_id,
                parent_id=parent_id if parent_id is not None else self.current_step_id,
                seq=0,
                kind=kind,
                name=name,
                status=status,
                started_at=now,
                ended_at=now,
                input=input,
                output=output,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                cache_hit=cache_hit,
                note=note,
            )
        )


# --------------------------------------------------------------------------------------------
# LangChain callback handler
# --------------------------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, BaseMessage):
        return _message(value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return str(value)


def _message(m: BaseMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.type, "content": _jsonable(m.content)}
    tool_calls = getattr(m, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = _jsonable(tool_calls)
    return out


def _model_name(serialized: dict[str, Any] | None, kwargs: dict[str, Any]) -> str | None:
    metadata = kwargs.get("metadata") or {}
    params = kwargs.get("invocation_params") or {}
    name = (
        metadata.get("ls_model_name")
        or params.get("model")
        or params.get("model_name")
        or kwargs.get("name")
        or (serialized or {}).get("name")
    )
    return str(name) if name else None


class TraceCallbackHandler(AsyncCallbackHandler):
    """Writes `llm` and `tool` trace events for every LangChain call it is attached to.

    Parent: `metadata["parent_id"]` if given, else the enclosing LangChain run (e.g. the agent
    step that called a tool), else the recorder's current step.
    """

    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder
        self._open_steps: dict[UUID, Step] = {}

    def _parent(self, parent_run_id: UUID | None, metadata: dict[str, Any] | None) -> str | None:
        if metadata and metadata.get("parent_id"):
            return str(metadata["parent_id"])
        if parent_run_id is not None and parent_run_id in self._open_steps:
            return self._open_steps[parent_run_id].id
        return self._recorder.current_step_id

    def _start(
        self,
        lc_run_id: UUID,
        name: str,
        kind: TraceKind,
        input: dict[str, Any],
        parent_run_id: UUID | None,
        metadata: dict[str, Any] | None,
        model: str | None = None,
    ) -> None:
        self._open_steps[lc_run_id] = self._recorder.open_step(
            name, kind, input, parent_id=self._parent(parent_run_id, metadata), model=model
        )

    def _finish(self, lc_run_id: UUID, status: TraceStatus, output: dict[str, Any]) -> Step | None:
        step = self._open_steps.pop(lc_run_id, None)
        if step is not None:
            step.output = output
            self._recorder.close_step(step, status)
        return step

    def _start_llm(
        self,
        serialized: dict[str, Any] | None,
        prompt: dict[str, Any],
        run_id: UUID,
        parent_run_id: UUID | None,
        metadata: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name") or "llm"
        model = _model_name(serialized, {"metadata": metadata, **kwargs})
        self._start(run_id, str(name), "llm", prompt, parent_run_id, metadata, model)

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        prompt = {"messages": [[_message(m) for m in batch] for batch in messages]}
        self._start_llm(serialized, prompt, run_id, parent_run_id, metadata, kwargs)

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start_llm(serialized, {"prompts": prompts}, run_id, parent_run_id, metadata, kwargs)

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        step = self._open_steps.get(run_id)
        if step is None:
            return
        texts: list[str] = []
        raw: list[Any] = []
        tokens_in = tokens_out = 0
        have_usage = False
        for batch in response.generations:
            for gen in batch:
                texts.append(gen.text)
                message = getattr(gen, "message", None)
                if isinstance(message, BaseMessage):
                    raw.append(_message(message))
                    usage = getattr(message, "usage_metadata", None)
                    if usage:
                        have_usage = True
                        tokens_in += int(usage.get("input_tokens", 0))
                        tokens_out += int(usage.get("output_tokens", 0))
        if have_usage:
            step.tokens_in, step.tokens_out = tokens_in, tokens_out
            step.cost_usd = get_settings().cost_usd(step.model, tokens_in, tokens_out)
        self._finish(run_id, "ok", {"text": "\n".join(texts), "messages": raw})

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish(run_id, "failed", {"error": describe_error(error)})

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name") or "tool"
        args = _jsonable(inputs) if inputs is not None else {"input": input_str}
        self._start(run_id, str(name), "tool", args, parent_run_id, metadata)

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = getattr(output, "content", output)
        self._finish(run_id, "ok", {"result": _jsonable(content)})

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._finish(run_id, "failed", {"error": describe_error(error)})
