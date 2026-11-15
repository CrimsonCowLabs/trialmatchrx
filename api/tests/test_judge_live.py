"""Real Sonnet judge of one criterion. Run with `uv run pytest -m live` and a key."""

import pytest

from app.config import get_settings
from app.pipeline.judge import JudgeItem, anthropic_judge_model, judge_criteria, new_judge_semaphore
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.test_judge import FACTS, INC_1, NCT, NOTE, TRIAL_TEXT


@pytest.mark.live
async def test_real_judge_of_one_criterion() -> None:
    if not get_settings().anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    rec = TraceRecorder(store.create_run("match", {}), EventBus())

    (verdict,) = await judge_criteria(
        rec,
        [JudgeItem(NCT, INC_1, TRIAL_TEXT)],
        FACTS,
        NOTE,
        semaphore=new_judge_semaphore(),
        model_factory=anthropic_judge_model,
    )

    assert verdict.outcome == "pass"
    assert verdict.verified
    (llm,) = [e for e in store.latest_events(rec.run_id) if e.kind == "llm"]
    assert llm.tokens_in and llm.cost_usd
