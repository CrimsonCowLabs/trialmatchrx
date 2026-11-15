"""GET /api/runs/{run_id}/events: stored events first, then live ones, then `done`."""

import asyncio
from collections.abc import Callable

from app.trace import store
from app.trace.bus import bus
from app.trace.recorder import TraceRecorder
from app.trace.runner import start_traced_run
from tests.sse import client, parse_sse


async def wait_for(predicate: Callable[[], bool]) -> None:
    """Poll a condition owned by the code under test (no hook to await on), up to 2 s."""
    async with asyncio.timeout(2.0):
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


async def test_late_subscriber_gets_stored_events_then_live_then_done() -> None:
    go_live = asyncio.Event()

    async def work(rec: TraceRecorder) -> None:
        rec.event("before-1", "step")
        rec.event("before-2", "step")
        await go_live.wait()
        rec.event("after-1", "step")
        rec.event("after-2", "step")
        return None

    run_id = start_traced_run("match", {}, work)
    await wait_for(lambda: len(store.load_events(run_id)) == 2)

    async with client() as c:
        response_task = asyncio.create_task(c.get(f"/api/runs/{run_id}/events"))
        # The stream has replayed what's stored and is now waiting on the bus.
        await wait_for(lambda: bus.subscriber_count(run_id) == 1)
        go_live.set()
        response = await response_task

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = parse_sse(response.text)
    traces = [m for m in messages if m.event == "trace"]
    assert [m.data["name"] for m in traces] == ["before-1", "before-2", "after-1", "after-2"]
    assert [m.data["seq"] for m in traces] == [1, 2, 3, 4]
    assert [m.id for m in traces] == ["1", "2", "3", "4"]
    assert messages[-1].event == "done"
    assert messages[-1].data == {"run_id": run_id, "status": "done"}


async def test_finished_run_replays_everything_then_done() -> None:
    async def work(rec: TraceRecorder) -> None:
        async with rec.step("only"):
            pass
        return None

    run_id = start_traced_run("match", {}, work)
    await wait_for(lambda: (r := store.get_run(run_id)) is not None and r.status == "done")

    async with client() as c:
        response = await c.get(f"/api/runs/{run_id}/events")

    messages = parse_sse(response.text)
    assert [(m.event, m.data.get("status")) for m in messages] == [
        ("trace", "started"),
        ("trace", "ok"),
        ("done", "done"),
    ]


async def test_reconnect_with_last_event_id_skips_what_was_seen() -> None:
    async def work(rec: TraceRecorder) -> None:
        for i in range(3):
            rec.event(f"e{i}", "step")
        return None

    run_id = start_traced_run("match", {}, work)
    await wait_for(lambda: (r := store.get_run(run_id)) is not None and r.status == "done")

    async with client() as c:
        response = await c.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "2"})

    assert [m.data["seq"] for m in parse_sse(response.text) if m.event == "trace"] == [3]


async def test_failed_run_ends_with_done_failed() -> None:
    async def work(rec: TraceRecorder) -> None:
        raise RuntimeError("upstream down")

    run_id = start_traced_run("match", {}, work)
    await wait_for(lambda: (r := store.get_run(run_id)) is not None and r.status == "failed")

    async with client() as c:
        messages = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)

    assert messages[-2].event == "trace" and messages[-2].data["kind"] == "error"
    assert messages[-1].data == {"run_id": run_id, "status": "failed"}


async def test_unknown_run_is_404() -> None:
    async with client() as c:
        response = await c.get("/api/runs/nope/events")
    assert response.status_code == 404
