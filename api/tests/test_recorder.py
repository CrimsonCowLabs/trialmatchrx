import asyncio

import pytest

from app.schemas import TraceEvent
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder


def new_recorder() -> tuple[TraceRecorder, EventBus]:
    bus = EventBus()
    run_id = store.create_run("match", {})
    return TraceRecorder(run_id, bus), bus


async def test_step_emits_started_then_ok_with_output() -> None:
    rec, _ = new_recorder()

    async with rec.step("compile_criteria", "step", {"nct": "NCT1"}) as s:
        s.output = {"criteria": 3}
        s.note = "3 criteria"

    started, done = store.load_events(rec.run_id)
    assert started.id == done.id
    assert (started.status, started.ended_at, started.output) == ("started", None, None)
    assert started.input == {"nct": "NCT1"}
    assert done.status == "ok"
    assert done.output == {"criteria": 3}
    assert done.note == "3 criteria"
    assert done.ended_at is not None and done.ended_at >= done.started_at


async def test_step_records_failure_and_reraises() -> None:
    rec, _ = new_recorder()

    with pytest.raises(ValueError, match="boom"):
        async with rec.step("judge", "llm"):
            raise ValueError("boom")

    final = store.latest_events(rec.run_id)[0]
    assert final.status == "failed"
    assert final.output == {"error": "ValueError: boom"}
    assert final.ended_at is not None


async def test_step_can_mark_itself_skipped() -> None:
    rec, _ = new_recorder()

    async with rec.step("judge", "llm") as s:
        s.status = "skipped"

    assert store.latest_events(rec.run_id)[0].status == "skipped"


async def test_nested_steps_get_their_parent_id_even_when_concurrent() -> None:
    rec, _ = new_recorder()

    async def trial(nct: str) -> None:
        async with rec.step(f"trial:{nct}"):
            await asyncio.sleep(0)
            async with rec.step(f"criterion:{nct}"):
                await asyncio.sleep(0)

    async with rec.step("run", "run") as root:
        await asyncio.gather(trial("A"), trial("B"))

    by_name = {e.name: e for e in store.latest_events(rec.run_id)}
    assert by_name["run"].parent_id is None
    assert by_name["trial:A"].parent_id == root.id
    assert by_name["trial:B"].parent_id == root.id
    assert by_name["criterion:A"].parent_id == by_name["trial:A"].id
    assert by_name["criterion:B"].parent_id == by_name["trial:B"].id


async def test_seq_is_monotonic_and_matches_publish_order() -> None:
    rec, bus = new_recorder()
    published: list[TraceEvent] = []

    async with bus.subscribe(rec.run_id) as sub:

        async def work(i: int) -> None:
            async with rec.step(f"s{i}"):
                await asyncio.sleep(0)

        await asyncio.gather(*(work(i) for i in range(5)))
        while not sub.empty():
            item = sub.get_nowait()
            assert isinstance(item, TraceEvent)
            published.append(item)

    assert [e.seq for e in published] == list(range(1, 11))
    assert [e.seq for e in store.load_events(rec.run_id)] == list(range(1, 11))


async def test_point_event_is_emitted_once_under_the_current_step() -> None:
    rec, _ = new_recorder()

    async with rec.step("evaluate") as s:
        ev = rec.event("rule:inc-1", "rule", input={"op": ">="}, output={"outcome": "pass"})

    events = store.load_events(rec.run_id)
    assert len(events) == 3
    assert ev.parent_id == s.id
    assert ev.status == "ok" and ev.ended_at is not None
