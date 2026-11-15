"""DEMO_MODE=replay end to end: /api/match and /api/closer replay the fixtures record_demo wrote,
twice in a row, with no model at all; the replayed runs keep "Why?" links and export."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.config import get_settings
from app.main import app
from app.pipeline.fixture_model import FixtureChatModel
from app.routers.match import closer_model_factory, judge_model_factory, parse_model_factory
from app.routers.trials import compile_model_factory
from app.schemas import CloserOutput, Health, RunSummary, TraceEvent
from app.trace import store
from app.trace.replay import RunFixture
from scripts.record_demo import record_closer, record_match
from tests.scripted_model import ScriptedChatModel
from tests.sse import SSEMessage, client, parse_sse
from tests.test_closer_agent import DEMO_OUTPUT, TRIAL, happy_script
from tests.test_match_run import BODY, cache_and_compile


def _no_model() -> Any:
    raise AssertionError("replay mode must not build a model")


@pytest.fixture
def replay_mode(tmp_path: Path) -> Iterator[Path]:
    """DEMO_MODE=replay over an (empty) fixtures dir, without gaps, and no model anywhere."""
    settings = get_settings()
    saved = settings.demo_mode, settings.demo_fixtures_dir, settings.demo_replay_max_gap_s
    settings.demo_mode = "replay"
    settings.demo_fixtures_dir = tmp_path / "runs"
    settings.demo_replay_max_gap_s = 0.0
    yield settings.demo_fixtures_dir
    settings.demo_mode, settings.demo_fixtures_dir, settings.demo_replay_max_gap_s = saved


@pytest.fixture
async def recorded(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> AsyncIterator[tuple[RunFixture, RunFixture]]:
    """The demo's match and closer runs, recorded by scripts/record_demo.py (no network)."""
    out = tmp_path / "runs"
    await cache_and_compile([TRIAL])
    match = await record_match(out, BODY, parse_model_factory=lambda: fixture_parse_model)
    closer = await record_closer(
        out, match.run_id, TRIAL, model=ScriptedChatModel(replies=happy_script(match.run_id))
    )
    factories = (parse_model_factory, judge_model_factory, compile_model_factory)
    for factory in (*factories, closer_model_factory):
        app.dependency_overrides[factory] = lambda: _no_model
    yield match, closer
    for factory in (*factories, closer_model_factory):
        app.dependency_overrides.pop(factory, None)


async def replayed(
    path: str, body: dict[str, Any]
) -> tuple[RunSummary, list[TraceEvent], list[SSEMessage]]:
    async with client() as c:
        started = await c.post(path, json=body)
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        streamed = parse_sse((await c.get(f"/api/runs/{run_id}/events")).text)
        summary = RunSummary.model_validate((await c.get(f"/api/runs/{run_id}")).json())
        trace = [
            TraceEvent.model_validate(e) for e in (await c.get(f"/api/runs/{run_id}/trace")).json()
        ]
    return summary, trace, streamed


def shape(events: list[TraceEvent]) -> list[tuple[str, str, str]]:
    return [(e.kind, e.name, e.status) for e in events]


def final(events: list[TraceEvent]) -> list[TraceEvent]:
    """One entry per event id in its last state, as `/trace` exports it."""
    return list({e.id: e for e in events}.values())


async def test_the_demo_replays_twice_in_a_row_without_a_model(
    replay_mode: Path, recorded: tuple[RunFixture, RunFixture]
) -> None:
    match_fx, closer_fx = recorded
    seen_runs: set[str] = set()
    for _ in range(2):
        match, trace, streamed = await replayed("/api/match", BODY)
        assert match.status == "done" and match.run_id not in seen_runs | {match_fx.run_id}
        seen_runs.add(match.run_id)
        # The same trace, streamed live and then `done`.
        assert [m.event for m in streamed][-1] == "done"
        streamed_events = [TraceEvent.model_validate(m.data) for m in streamed[:-1]]
        assert shape(streamed_events) == shape(match_fx.events)
        assert shape(trace) == shape(final(match_fx.events))
        assert [m.nct_id for m in match.matches] == [TRIAL]
        # "Why?": every verdict points at an event of this run's exported trace.
        ids = {e.id for e in trace}
        assert all(v.trace_event_id in ids for m in match.matches for v in m.verdicts)

        closer, closer_trace, _ = await replayed(
            "/api/closer", {"run_id": match.run_id, "nct_id": TRIAL}
        )
        assert closer.status == "done"
        assert closer.closer == CloserOutput.model_validate(DEMO_OUTPUT)
        assert shape(closer_trace) == shape(final(closer_fx.events))
        tools = [e for e in closer_trace if e.kind == "tool" and e.input and "run_id" in e.input]
        assert {e.input["run_id"] for e in tools if e.input} == {match.run_id}  # the replayed run


async def test_any_match_request_replays_the_recorded_demo(
    replay_mode: Path, recorded: tuple[RunFixture, RunFixture]
) -> None:
    match, _, _ = await replayed("/api/match", {**BODY, "note": "61M, T2D, slightly reworded"})
    assert [m.nct_id for m in match.matches] == [TRIAL]
    # The run keeps the request that was recorded, so its request, parse and trace agree.
    run = store.get_run(match.run_id)
    assert run is not None and run.request == recorded[0].request


@pytest.fixture
def broken_fixture(replay_mode: Path) -> Path:
    replay_mode.mkdir(parents=True)
    (path := replay_mode / "match.json").write_text("{not json")
    return path


async def test_a_broken_fixture_file_makes_health_not_ok(broken_fixture: Path) -> None:
    async with client() as c:
        response = await c.get("/api/health")
    assert response.status_code == 200 and not Health.model_validate(response.json()).ok


async def test_replay_without_fixtures_is_503(replay_mode: Path) -> None:
    async with client() as c:
        response = await c.post("/api/match", json=BODY)
        health = Health.model_validate((await c.get("/api/health")).json())
    assert response.status_code == 503
    assert "record_demo" in response.json()["detail"]
    assert health.demo_mode == "replay" and not health.ok


async def test_closer_on_a_trial_with_no_recording_is_503(
    replay_mode: Path, recorded: tuple[RunFixture, RunFixture]
) -> None:
    match, _, _ = await replayed("/api/match", BODY)
    (replay_mode / f"closer-{TRIAL}.json").unlink()
    async with client() as c:
        response = await c.post("/api/closer", json={"run_id": match.run_id, "nct_id": TRIAL})
    assert response.status_code == 503
    assert TRIAL in response.json()["detail"] and "record_demo" in response.json()["detail"]


async def test_health_reports_replay_mode_and_model_ids(
    replay_mode: Path, recorded: tuple[RunFixture, RunFixture]
) -> None:
    async with client() as c:
        health = Health.model_validate((await c.get("/api/health")).json())
    assert health.ok and health.demo_mode == "replay"
    assert health.model_ids == get_settings().model_ids()
