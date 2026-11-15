"""Access barrier flags: rule-based patterns over a criterion's verbatim text. No network."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.pipeline import criteria_cache
from app.pipeline.access_barriers import classify
from app.pipeline.compile_criteria import PROMPT_NAME, compile_study
from app.pipeline.fixture_model import FixtureChatModel
from app.pipeline.match_run import match_trial
from app.pipeline.trial_search import CandidateTrial
from app.prompts import load_prompt
from app.schemas import Criterion, PatientFacts, TraceEvent, TrialDetail
from app.sources import ctgov
from app.trace import store
from app.trace.bus import EventBus
from app.trace.recorder import TraceRecorder
from tests.ctgov_fake import load
from tests.sse import client

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "access_barriers" / "criteria.json").read_text()
)["cases"]

NCT = "NCT00000053"
ELIGIBILITY = {"eligibilityCriteria": "* Able to read and write English\n* HbA1c >= 7%"}
STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": NCT},
        "eligibilityModule": ELIGIBILITY,
    }
}


def criterion(crit_id: str, text: str) -> Criterion:
    return Criterion(
        id=crit_id,
        type="inclusion",
        text=text,
        category="other",
        predicate=None,
        needs_judgment=True,
    )


# Criteria as a compile before #53 stored them: no access_barrier key at all.
PRE_FLAG_ROW = [
    {k: v for k, v in criterion(i, t).model_dump(mode="json").items() if k != "access_barrier"}
    for i, t in [("inc-1", "Able to read and write English"), ("inc-2", "HbA1c >= 7%")]
]


def recorder() -> TraceRecorder:
    return TraceRecorder(store.create_run("compile", {}), EventBus())


def named(rec: TraceRecorder, name: str) -> TraceEvent:
    (event,) = [e for e in store.latest_events(rec.run_id) if e.name == name]
    return event


def seed_pre_flag_cache() -> None:
    """A compile cache row written before the flag existed (same hash and prompt version)."""
    key = criteria_cache.eligibility_hash(ELIGIBILITY)
    version = load_prompt(PROMPT_NAME).version
    old = [Criterion.model_validate(c) for c in PRE_FLAG_ROW]
    criteria_cache.put(NCT, key, version, "old-model", old)


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:60] for c in CASES])
def test_criterion_text_gets_its_barrier_or_none(case: dict[str, Any]) -> None:
    assert classify(case["text"]) == case["barrier"]


async def test_cached_criteria_are_flagged_without_recompiling() -> None:
    seed_pre_flag_cache()
    model = FixtureChatModel(output={"criteria": []})
    rec = recorder()

    criteria = await compile_study(STUDY, rec, model_factory=lambda: model)

    assert [(c.id, c.access_barrier) for c in criteria] == [("inc-1", "language"), ("inc-2", None)]
    assert model.calls == 0
    assert named(rec, "cache_lookup").cache_hit is True


async def test_classification_is_a_traced_rule_step() -> None:
    seed_pre_flag_cache()
    rec = recorder()

    await compile_study(STUDY, rec, model_factory=lambda: FixtureChatModel(output={}))

    step = named(rec, "access_barriers")
    assert (step.kind, step.status) == ("rule", "ok")
    assert step.parent_id == named(rec, "compile_criteria").id
    assert step.output == {
        "flagged": {"inc-1": {"barrier": "language", "match": "read and write English"}}
    }
    assert step.note == f"{NCT}: 1 access barrier (inc-1 language)"


async def test_match_verdicts_carry_their_criterion_barrier() -> None:
    seed_pre_flag_cache()
    trial = CandidateTrial(nct_id=NCT, title="T", phase=None, distance_mi=None, study=STUDY)
    facts = PatientFacts(
        age=61, sex="male", conditions=[], labs={}, vitals={}, meds=[],
        pregnant=None, smoker=None, lat=None, lon=None,
    )  # fmt: skip

    match = await match_trial(recorder(), trial, facts)

    assert match is not None
    assert [(v.criterion_id, v.access_barrier) for v in match.verdicts] == [
        ("inc-1", "language"),
        ("inc-2", None),
    ]


async def test_trial_api_serves_cached_criteria_flagged_and_traced() -> None:
    study = load("study.json")
    nct = study["protocolSection"]["identificationModule"]["nctId"]
    ctgov.cache_study(study)
    old = [Criterion.model_validate(c) for c in PRE_FLAG_ROW]
    criteria_cache.put(nct, "any-hash", "any-version", None, old)

    async with client() as c:
        resp = await c.get(f"/api/trials/{nct}")
        trace = (await c.get(f"/api/runs/{resp.headers['x-run-id']}/trace")).json()

    trial = TrialDetail.model_validate(resp.json())
    assert [(c.id, c.access_barrier) for c in trial.criteria] == [
        ("inc-1", "language"),
        ("inc-2", None),
    ]
    steps = [TraceEvent.model_validate(e) for e in trace if e["name"] == "access_barriers"]
    assert [(e.kind, e.status) for e in steps] == [("rule", "ok")]
