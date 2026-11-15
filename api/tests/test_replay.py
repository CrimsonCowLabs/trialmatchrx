"""Demo replay (DEMO_MODE=replay): a recorded run fixture re-emitted into a fresh run, with its
original timing (gaps capped) and every id remapped so two replays never collide."""

import datetime as dt
from typing import Any

from app.schemas import TraceEvent, TraceKind, TraceStatus
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from app.trace.replay import RunFixture, replay_run

T0 = dt.datetime(2026, 11, 11, 20, 0, tzinfo=dt.UTC)
RECORDED_RUN = "11111111-1111-4111-8111-111111111111"
STEP = "22222222-2222-4222-8222-222222222222"
RULE = "33333333-3333-4333-8333-333333333333"


def emission(
    seq: int,
    event_id: str,
    status: TraceStatus,
    started_s: float,
    ended_s: float | None,
    *,
    kind: TraceKind = "step",
    parent_id: str | None = None,
    **fields: Any,
) -> TraceEvent:
    return TraceEvent(
        id=event_id,
        run_id=RECORDED_RUN,
        parent_id=parent_id,
        seq=seq,
        kind=kind,
        name=fields.pop("name", f"{kind}-{seq}"),
        status=status,
        started_at=T0 + dt.timedelta(seconds=started_s),
        ended_at=None if ended_s is None else T0 + dt.timedelta(seconds=ended_s),
        input=fields.pop("input", None),
        output=fields.pop("output", None),
        model=None,
        tokens_in=None,
        tokens_out=None,
        cost_usd=None,
        note=None,
    )


def fixture(events: list[TraceEvent], result: dict[str, Any] | None = None) -> RunFixture:
    return RunFixture(
        run_id=RECORDED_RUN,
        kind="match",
        request={"note": "61M"},
        result=result or {},
        recorded_at=T0,
        events=events,
    )


# A step that ran 3 s with a rule inside it at 0.05 s: emissions at 0, 0.05, 3.0.
EVENTS = [
    emission(1, STEP, "started", 0, None),
    emission(2, RULE, "ok", 0.05, 0.05, kind="rule", parent_id=STEP),
    emission(3, STEP, "ok", 0, 3.0),
]


async def replay(
    fx: RunFixture, max_gap_s: float = 0.2, **kwargs: Any
) -> tuple[str, dict[str, Any] | None, list[float]]:
    run_id = store.create_run(fx.kind, fx.request)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    result = await replay_run(
        TraceRecorder(run_id, EventBus()), fx, max_gap_s=max_gap_s, sleep=sleep, **kwargs
    )
    return run_id, result, slept


async def test_events_are_re_emitted_in_order_with_gaps_capped() -> None:
    run_id, _, slept = await replay(fixture(EVENTS), max_gap_s=0.2)

    replayed = store.load_events(run_id)
    assert [(e.seq, e.kind, e.status) for e in replayed] == [
        (1, "step", "started"),
        (2, "rule", "ok"),
        (3, "step", "ok"),
    ]
    assert slept == [0.05, 0.2]  # the 2.95 s wait is capped at 0.2 s


SOURCE_RUN = "44444444-4444-4444-8444-444444444444"  # e.g. the match run a closer run read


async def test_each_replay_gets_fresh_ids_wired_through_events_and_result() -> None:
    events = [
        *EVENTS[:2],
        emission(
            3,
            STEP,
            "ok",
            0,
            3.0,
            input={"prompt": f"Match run {SOURCE_RUN}, see {RULE}", "run_id": RECORDED_RUN},
        ),
    ]
    fx = fixture(events, result={"matches": [{"verdicts": [{"trace_event_id": RULE}]}]})
    live_source = "55555555-5555-4555-8555-555555555555"

    first_id, first_result, _ = await replay(fx, ids={SOURCE_RUN: live_source})
    second_id, second_result, _ = await replay(fx, ids={SOURCE_RUN: live_source})

    first, second = store.latest_events(first_id), store.latest_events(second_id)
    step, rule = first
    assert {step.id, rule.id}.isdisjoint({STEP, RULE})  # fresh ids...
    assert {e.id for e in first}.isdisjoint({e.id for e in second})  # ...on every replay
    assert rule.parent_id == step.id and all(e.run_id == first_id for e in first)
    assert step.input == {"prompt": f"Match run {live_source}, see {rule.id}", "run_id": first_id}
    # "Why?" on a replayed verdict lands on the replayed rule event.
    assert first_result == {"matches": [{"verdicts": [{"trace_event_id": rule.id}]}]}
    assert second_result is not None
    assert second_result["matches"][0]["verdicts"][0]["trace_event_id"] == second[1].id
