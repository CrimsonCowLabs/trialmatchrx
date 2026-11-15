"""All 10 saved T2D/CKD trials compile to valid Criterion lists on saved LLM outputs.

The LLM outputs in fixtures/compile/llm/ are hand-authored (no API key yet), so these tests
check the compiler and the fixtures' fidelity to the real trial text, not Sonnet's quality.
"""

import pytest

from app.pipeline.compile_criteria import compile_rate, compile_study
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.study_source import StudyNotFound, fixture_nct_ids, load_fixture_study
from app.schemas import Criterion
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder

NCT_IDS = fixture_nct_ids()


def test_there_are_ten_fixture_trials_each_with_a_saved_llm_output() -> None:
    assert len(NCT_IDS) == 10
    for nct in NCT_IDS:
        assert load_llm_fixture(nct)["criteria"]


@pytest.mark.parametrize("nct", NCT_IDS)
async def test_fixture_trial_compiles_to_valid_criteria(nct: str) -> None:
    study = load_fixture_study(nct)
    rec = TraceRecorder(store.create_run("compile", {"nct": nct}), EventBus())
    model = FixtureChatModel(output=load_llm_fixture(nct))

    criteria = await compile_study(study, rec, model_factory=lambda: model)

    assert model.calls == 1
    assert criteria == [Criterion.model_validate(c.model_dump()) for c in criteria]
    ids = [c.id for c in criteria]
    assert len(ids) == len(set(ids))
    assert "inc-age-min" in ids  # every fixture trial has a minimum age
    for c in criteria:
        assert c.needs_judgment == (c.predicate is None)
    # Hand-authored fixtures must be verbatim and only use valid predicates: no guardrail trips.
    guardrails = [e for e in store.latest_events(rec.run_id) if e.kind == "guardrail"]
    assert guardrails == []
    rate = compile_rate(criteria)
    assert rate is not None and 0 < rate < 1


async def test_unknown_study_is_not_found() -> None:
    with pytest.raises(StudyNotFound):
        load_fixture_study("NCT99999999")
    with pytest.raises(StudyNotFound):
        load_fixture_study("../secrets")
