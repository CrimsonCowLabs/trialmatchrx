"""`run_eval --fail-fast`: stop the eval at the first model failure (issue #60).

    watch = FailFastWatch(topic.id)
    task = asyncio.create_task(match_the_topic(bus=watch))   # its traced run publishes here
    watch.watch(task)
    ...                       # the first failure cancels `task`; `watch.failure` says what broke

The pipeline handles most model failures itself and carries on (a trial that can't compile is
skipped, a judge call that errors becomes `unknown`), which is right for a live match. The eval
sees them on the run's trace instead: `FailFastWatch` is the event bus of each topic's match run,
and the first failed event that is not a guardrail (a failed step, LLM call or error event)
cancels the topic's task. Guardrails (an invalid predicate, an unverified quote) are not model
failures: the answer is kept, downgraded, and replays the same.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from app.pipeline import compile_criteria, judge, match_run, parse_patient
from app.schemas import TraceEvent
from app.trace.bus import EventBus


@dataclass(frozen=True)
class FailFastStop:
    """Where the eval stopped: the first model failure of the run."""

    step: str  # parse, compile or judge (else the failed event's name)
    topic_id: int
    nct_id: str | None  # the trial, for a compile or judge failure
    error: str
    run_id: str


def _step(name: str) -> str | None:
    if name == parse_patient.STEP_NAME:
        return "parse"
    if name in (compile_criteria.STEP_NAME, compile_criteria.LLM_SPLIT_STEP):
        return "compile"
    if name.startswith(judge.STEP_PREFIX):
        return "judge"
    return None


class FailFastWatch(EventBus):
    """The event bus of one topic's match run that also cancels the watched task at the first
    failed event, and says where it stopped (`failure`)."""

    def __init__(self, topic_id: int) -> None:
        super().__init__()
        self.topic_id = topic_id
        self.failure: FailFastStop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._events: dict[str, TraceEvent] = {}

    def watch(self, task: asyncio.Task[Any]) -> None:
        self._task = task

    def publish(self, event: TraceEvent) -> None:
        super().publish(event)
        self._events[event.id] = event
        if self.failure is None and event.status == "failed" and event.kind != "guardrail":
            self.failure = self._describe(event)
            if self._task is not None:
                self._task.cancel("--fail-fast")

    def _describe(self, event: TraceEvent) -> FailFastStop:
        """The failure's step (the nearest parse / compile / judge step at or above the failed
        event) and trial (the nearest `trial:<nct>` step)."""
        step: str | None = None
        nct: str | None = None
        current: TraceEvent | None = event
        while current is not None:
            step = step or _step(current.name)
            if nct is None and current.name.startswith(match_run.TRIAL_STEP_PREFIX):
                nct = current.name.removeprefix(match_run.TRIAL_STEP_PREFIX)
            current = self._events.get(current.parent_id) if current.parent_id else None
        output = event.output or {}
        error = str(output.get("error") or event.note or event.name)
        return FailFastStop(step or event.name, self.topic_id, nct, error, event.run_id)
