"""Real Sonnet compile of one fixture trial. Run with `uv run pytest -m live` and a key."""

import pytest

from app.config import get_settings
from app.pipeline.compile_criteria import anthropic_compile_model, compile_study
from app.pipeline.study_source import load_study
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder


@pytest.mark.live
async def test_real_compile_of_one_trial() -> None:
    if not get_settings().anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    rec = TraceRecorder(store.create_run("compile", {}), EventBus())

    criteria = await compile_study(
        await load_study("NCT07271186"), rec, model_factory=anthropic_compile_model
    )

    assert any(c.id.startswith("inc-") and c.id[4:].isdigit() for c in criteria)
    (llm,) = [e for e in store.latest_events(rec.run_id) if e.kind == "llm"]
    assert llm.tokens_in and llm.cost_usd
