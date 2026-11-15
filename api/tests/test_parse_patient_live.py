"""Real Haiku parse of the demo note. Run with `uv run pytest -m live` and a key."""

from pathlib import Path

import pytest

from app.config import get_settings
from app.pipeline.parse_patient import anthropic_parse_model, parse_patient
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

NOTE = (Path(__file__).parent / "fixtures" / "parse_patient" / "demo_short.txt").read_text()


@pytest.mark.live
async def test_real_parse_of_the_demo_patient() -> None:
    if not get_settings().anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set")
    rec = TraceRecorder(store.create_run("match", {}), EventBus())

    facts = await parse_patient(rec, NOTE, model_factory=anthropic_parse_model)

    assert facts.age == 61 and facts.sex == "male"
    assert facts.labs["hba1c"].value == 8.4 and facts.labs["egfr"].value == 48
    assert any("metformin" in str(m.value) for m in facts.meds)
    listed = [*facts.conditions, *facts.meds, *facts.labs.values(), *facts.vitals.values()]
    assert all(f.source_span and f.source_span in NOTE for f in listed)
