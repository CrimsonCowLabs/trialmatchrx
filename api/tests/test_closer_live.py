"""Real Sonnet closer agent on the demo patient's top trial. Run with `uv run pytest -m live`
and a key. The match run itself comes from saved fixtures (compile cache, parsed note)."""

import pytest

from app.config import get_settings
from app.trace import store
from tests.sse import client, parse_sse
from tests.test_closer_agent import run_closer
from tests.test_match_run import BODY, NEAR, cache_and_compile


@pytest.mark.live
async def test_real_closer_on_the_demo_patients_top_trial() -> None:
    if not get_settings().anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    await cache_and_compile(NEAR)
    async with client() as c:
        match_id = (await c.post("/api/match", json=BODY)).json()["run_id"]
        parse_sse((await c.get(f"/api/runs/{match_id}/events")).text)
    match = store.get_run(match_id)
    assert match is not None and match.result
    top = match.result["matches"][0]

    summary, _, trace = await run_closer(match_id, top["nct_id"])

    assert summary.status == "done", [e.output for e in trace if e.kind == "error"]
    assert summary.closer is not None
    assert summary.closer.patient_summary.en and summary.closer.patient_summary.es
    assert summary.closer.coordinator_email.body
    coverage = next(e for e in trace if e.name == "closer:followup_coverage")
    assert coverage.status == "ok", coverage.output  # a follow-up for each unknown criterion
    assert {e.name for e in trace if e.kind == "tool"} >= {
        "get_match_result",
        "get_unknown_criteria",
        "get_trial_contacts",
        "get_patient_facts",
    }
