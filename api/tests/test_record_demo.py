"""scripts/record_demo.py: the demo patient's match run and closer run, recorded into run
fixtures. No network: trials and criteria come from saved fixtures, the closer model is
scripted (tests/test_closer_agent.py)."""

import json
from pathlib import Path

import pytest

from app.pipeline.fixture_model import FixtureChatModel
from app.trace import store
from app.trace.replay import RunFixture, load_fixtures
from scripts.record_demo import (
    DEMO_PATIENTS,
    describe,
    llm_cost,
    patient_for_note,
    record_closer,
    record_match,
    save_runs,
)
from tests.scripted_model import ScriptedChatModel
from tests.test_closer_agent import DEMO_OUTPUT, TRIAL, happy_script
from tests.test_match_run import BODY, cache_and_compile


async def record_demo_match(out: Path, parse_model: FixtureChatModel) -> RunFixture:
    """The demo note, parsed by the saved Haiku output, against the cached fixture trial."""
    await cache_and_compile([TRIAL])
    return await record_match(out, BODY, parse_model_factory=lambda: parse_model)


async def test_record_match_writes_the_whole_run_as_a_fixture(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    fixture = await record_demo_match(tmp_path, fixture_parse_model)

    saved = RunFixture.model_validate(json.loads((tmp_path / "match-t2d.json").read_text()))
    assert saved == fixture
    assert saved.kind == "match" and saved.request["note"] == BODY["note"]
    assert [m["nct_id"] for m in (saved.result or {})["matches"]] == [TRIAL]
    # Every emission as stored, started and final states alike, in seq order.
    assert saved.events == store.load_events(saved.run_id)
    assert {e.status for e in saved.events} >= {"started", "ok"}
    verdict_events = {v["trace_event_id"] for v in (saved.result or {})["matches"][0]["verdicts"]}
    assert verdict_events <= {e.id for e in saved.events}  # "Why?" resolves inside the fixture


async def test_record_closer_writes_the_agent_run_for_one_trial(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    match = await record_demo_match(tmp_path, fixture_parse_model)
    model = ScriptedChatModel(replies=happy_script(match.run_id))

    fixture = await record_closer(tmp_path, match.run_id, TRIAL, model=model)

    assert (tmp_path / "closer-t2d.json").exists()
    assert fixture.kind == "closer"
    assert fixture.request == {"run_id": match.run_id, "nct_id": TRIAL}
    assert (fixture.result or {})["closer"] == DEMO_OUTPUT
    assert sorted(f.kind for f in load_fixtures(tmp_path)) == ["closer", "match"]


async def test_a_failed_run_is_not_saved(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    match = await record_demo_match(tmp_path, fixture_parse_model)
    broken = ScriptedChatModel(replies=happy_script(match.run_id, output={"nct_id": TRIAL}))

    with pytest.raises(RuntimeError, match="failed"):
        await record_closer(tmp_path, match.run_id, TRIAL, model=broken)
    assert not (tmp_path / "closer-t2d.json").exists()


async def test_finished_runs_in_the_database_can_be_saved_offline(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    """`--from-runs`: a rehearsal done in the UI becomes the fixtures, no model needed."""
    match = await record_demo_match(tmp_path / "live", fixture_parse_model)
    model = ScriptedChatModel(replies=happy_script(match.run_id))
    closer = await record_closer(tmp_path / "live", match.run_id, TRIAL, model=model)

    with pytest.raises(RuntimeError, match="pass --patient"):  # BODY is no demo note
        save_runs(tmp_path / "saved", match.run_id, closer.run_id)
    save_runs(tmp_path / "saved", match.run_id, closer.run_id, patient="t2d")

    assert load_fixtures(tmp_path / "saved") == load_fixtures(tmp_path / "live")
    with pytest.raises(RuntimeError, match="expected a match run and a closer run"):
        save_runs(tmp_path / "bad", closer.run_id, match.run_id)


def test_demo_patients_are_found_by_note() -> None:
    assert sorted(DEMO_PATIENTS) == ["als", "ipf", "pah", "t2d"]
    for patient, request in DEMO_PATIENTS.items():
        assert patient_for_note("  " + request["note"].upper() + "\n") == patient
    assert patient_for_note("someone else") is None


async def test_the_llm_cost_comes_from_the_trace(
    tmp_path: Path, no_api_key: None, fixture_parse_model: FixtureChatModel
) -> None:
    fixture = await record_demo_match(tmp_path, fixture_parse_model)
    final = {e.id: e for e in fixture.events if e.kind == "llm"}.values()
    costs = [e.cost_usd for e in final if e.cost_usd is not None]
    assert llm_cost(fixture) == (sum(costs) if costs else None)
    assert "LLM cost" in describe(fixture)
