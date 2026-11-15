"""GET /api/runs/stats: wall time and cost of recent finished match runs, from stored runs."""

import datetime as dt

from app.db import RunRow, session_scope
from app.schemas import RunKind, RunStats
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.sse import client

T0 = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.UTC)


def _finished_run(
    wall_s: float,
    costs: tuple[float, ...] = (),
    *,
    kind: RunKind = "match",
    status: str = "done",
    start: dt.datetime = T0,
) -> str:
    """A stored run that took `wall_s` seconds, with one `llm` event per cost."""
    rec = TraceRecorder(store.create_run(kind, {}), EventBus())
    for i, cost in enumerate(costs):
        rec.event(f"llm-{i}", "llm", cost_usd=cost, tokens_in=10, tokens_out=5)
    with session_scope() as s:
        run = s.get(RunRow, rec.run_id)
        assert run is not None
        run.status = status
        run.created_at = start
        run.ended_at = start + dt.timedelta(seconds=wall_s)
        s.add(run)
    return rec.run_id


async def _stats(**params: int) -> RunStats:
    async with client() as c:
        resp = await c.get("/api/runs/stats", params=params)
    assert resp.status_code == 200
    return RunStats.model_validate(resp.json())


async def test_no_runs_gives_empty_stats() -> None:
    assert await _stats() == RunStats(
        runs=0, wall_time_min_s=None, wall_time_max_s=None, cost_usd_median=None
    )


async def test_running_and_failed_runs_are_not_counted() -> None:
    store.create_run("match", {})
    _finished_run(5.0, (0.1,), status="failed")

    assert (await _stats()).runs == 0


async def test_other_kinds_are_not_counted() -> None:
    _finished_run(3.0, (0.5,), kind="closer")
    _finished_run(1.0, kind="compile")

    assert (await _stats()).runs == 0


async def test_wall_time_range_and_median_cost_of_finished_match_runs() -> None:
    _finished_run(12.0, (0.05, 0.05))  # 0.10
    _finished_run(30.5, (0.25,))  # 0.25
    _finished_run(18.0, (0.02, 0.03, 0.03))  # 0.08

    stats = await _stats()

    assert stats.runs == 3
    assert stats.wall_time_min_s == 12.0
    assert stats.wall_time_max_s == 30.5
    assert stats.cost_usd_median is not None
    assert abs(stats.cost_usd_median - 0.10) < 1e-9


async def test_median_of_an_even_count_is_the_mean_of_the_middle_two() -> None:
    for cost in (0.1, 0.2, 0.4, 0.9):
        _finished_run(10.0, (cost,))

    median = (await _stats()).cost_usd_median

    assert median is not None and abs(median - 0.3) < 1e-9


async def test_a_run_without_llm_events_costs_zero() -> None:
    _finished_run(2.0)

    assert (await _stats()).cost_usd_median == 0.0


async def test_only_the_most_recent_finished_runs_count() -> None:
    _finished_run(100.0, (9.0,), start=T0)  # oldest: dropped by limit=2
    _finished_run(10.0, (0.1,), start=T0 + dt.timedelta(hours=1))
    _finished_run(20.0, (0.3,), start=T0 + dt.timedelta(hours=2))
    store.create_run("match", {})  # newest, still running: neither counted nor using a slot

    stats = await _stats(limit=2)

    assert (stats.runs, stats.wall_time_min_s, stats.wall_time_max_s) == (2, 10.0, 20.0)
    assert stats.cost_usd_median is not None and abs(stats.cost_usd_median - 0.2) < 1e-9


async def test_limit_is_bounded() -> None:
    async with client() as c:
        assert (await c.get("/api/runs/stats", params={"limit": 0})).status_code == 422
        assert (await c.get("/api/runs/stats", params={"limit": 201})).status_code == 422
        assert (await c.get("/api/runs/stats", params={"limit": 200})).status_code == 200


async def test_stats_are_read_only() -> None:
    run_id = _finished_run(4.0, (0.1,))
    before = store.load_events(run_id)

    await _stats()

    assert [r.id for r in store.list_runs("match", 50)] == [run_id]
    assert store.load_events(run_id) == before
