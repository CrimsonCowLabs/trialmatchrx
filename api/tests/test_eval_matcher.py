"""The full matcher scored on a hand-built TREC sample (no network: fixture LLMs, hand-scored).

Two topics, four trials, every criterion one eGFR rule or one judged consent line:

    NCT01  inclusion  eGFR >= 30                    (rule)
    NCT02  exclusion  eGFR < 45                     (rule)
    NCT03  inclusion  Able to give informed consent (judge)
    NCT04  inclusion  eGFR >= 60                    (rule)
"""

from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from app.eval.matcher import score_matcher
from app.pipeline.compile_criteria import CompileModelUnavailable
from app.pipeline.fixture_model import FixtureChatModel
from app.sources.trec import Judgment, Topic, TrecSample
from app.trace import store

EGFR = "mL/min/1.73m2"
CONSENT = "Able to give informed consent"
NOTE_1 = "58F with type 2 diabetes, eGFR 40, consents to research."
NOTE_2 = "70M with gout, eGFR 75."


class ByMarker(FixtureChatModel):
    """Answers with the output whose marker appears in the prompt (an NCT ID, a note)."""

    by_marker: dict[str, dict[str, Any]] = {}

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        prompt = "".join(str(m.content) for m in messages)
        self.output = next(out for marker, out in self.by_marker.items() if marker in prompt)
        return super()._result(messages)


def _egfr(op: str, value: float) -> dict[str, Any]:
    return {"field": "labs.egfr", "op": op, "value": value, "unit": EGFR}


def _criterion(kind: str, text: str, predicate: dict[str, Any] | None) -> dict[str, Any]:
    category = "lab" if predicate else "other"
    return {"type": kind, "text": text, "category": category, "predicate": predicate}


CRITERIA = {
    "NCT01": _criterion("inclusion", "eGFR >= 30", _egfr(">=", 30)),
    "NCT02": _criterion("exclusion", "eGFR < 45", _egfr("<", 45)),
    "NCT03": _criterion("inclusion", CONSENT, None),
    "NCT04": _criterion("inclusion", "eGFR >= 60", _egfr(">=", 60)),
}


def _patient(age: str, sex: str, egfr: int) -> dict[str, Any]:
    head = f"{age}{sex[0].upper()}"
    return {
        "age": {"value": int(age), "source_span": head},
        "sex": {"value": sex, "source_span": head},
        "conditions": [],
        "labs": [{"name": "egfr", "value": egfr, "unit": EGFR, "source_span": f"eGFR {egfr}"}],
        "vitals": [],
        "meds": [],
        "pregnant": None,
        "smoker": None,
        "location": None,
    }


def _study(nct: str) -> dict[str, Any]:
    kind, text = CRITERIA[nct]["type"], CRITERIA[nct]["text"]
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"Trial {nct}"},
            "eligibilityModule": {"eligibilityCriteria": f"{kind.title()} Criteria:\n* {text}"},
        }
    }


def _sample() -> TrecSample:
    labels = {
        1: {"NCT01": 2, "NCT02": 1, "NCT03": 2, "NCT04": 0},
        2: {"NCT04": 2, "NCT01": 1, "NCT02": 0},
    }
    return TrecSample(
        seed=1,
        n_topics=2,
        per_topic=4,
        topics=[Topic(id=1, text=NOTE_1), Topic(id=2, text=NOTE_2)],
        judgments=[
            Judgment.model_validate({"topic_id": t, "nct_id": nct, "label": label})
            for t, by_nct in labels.items()
            for nct, label in by_nct.items()
        ],
        trials={nct: _study(nct) for nct in CRITERIA},
        dropped={},
    )


class Models:
    """Fresh fixture models, as a new `make eval` process would build them."""

    def __init__(self) -> None:
        self.compile = ByMarker(
            output={"criteria": []}, by_marker={n: {"criteria": [c]} for n, c in CRITERIA.items()}
        )
        self.parse = ByMarker(
            output={"x": 1},
            tool_name="DraftPatient",
            model_name="parse-model",
            by_marker={"58F": _patient("58", "female", 40), "70M": _patient("70", "male", 75)},
        )
        self.judge = FixtureChatModel(
            output={
                "outcome": "pass",
                "criterion_quote": CONSENT,
                "patient_evidence": "consents to research",
                "rationale": "The note says the patient consents.",
            },
            tool_name="JudgeOutput",
            model_name="judge-model",
        )

    def score(self, sample: TrecSample) -> Any:
        return score_matcher(
            sample,
            compile_model_factory=lambda: self.compile,
            parse_model_factory=lambda: self.parse,
            judge_model_factory=lambda: self.judge,
        )

    @property
    def calls(self) -> tuple[int, int, int]:
        return self.compile.calls, self.parse.calls, self.judge.calls


async def test_matcher_scores_the_sample_by_hand() -> None:
    models = Models()
    score = await models.score(_sample())

    # Topic 1 (eGFR 40, consents): NCT01 and NCT03 likely, NCT02 (excluded below 45) and NCT04
    # (needs 60) ineligible -> labels [2, 2, 1, 0]: nDCG 1.0, P@10 0.2.
    # Topic 2 (eGFR 75, no consent line): all three likely with no unknowns, so NCT order ->
    # labels [1, 0, 2]: nDCG 1/log2(4) = 0.5, P@10 0.1.
    assert score.rankings == {
        1: ["NCT01", "NCT03", "NCT02", "NCT04"],
        2: ["NCT01", "NCT02", "NCT04"],
    }
    assert score.metrics == {
        "ndcg@10": pytest.approx(0.75),
        "p@10": pytest.approx(0.15),
        # Labels 1/2 called right: T1 NCT01, NCT02, NCT03; T2 NCT04. Wrong: T2 NCT01 (label 1
        # but passes eGFR >= 30) -> 4/5.
        "accuracy": pytest.approx(0.8),
        # 3 of the 4 trials' criteria are rules; the consent line needs the judge.
        "compile_rate": pytest.approx(0.75),
    }
    assert score.uncompiled == []
    # Each trial compiled once, one parse per topic, one judge call (NCT03 is only judged
    # against topic 1).
    assert models.calls == (4, 2, 1)


async def test_each_topic_is_a_traced_match_run() -> None:
    score = await Models().score(_sample())

    runs = {topic: store.get_run(run_id) for topic, run_id in score.run_ids.items()}
    assert sorted(runs) == [1, 2]
    for topic, run in runs.items():
        assert run is not None and run.kind == "match" and run.status == "done"
        assert run.request["eval"] == {"topic": topic}


async def test_a_rerun_with_a_warm_cache_is_reproducible_without_calling_a_model() -> None:
    first = await Models().score(_sample())

    again = Models()
    second = await again.score(_sample())

    assert second.metrics == first.metrics
    assert second.rankings == first.rankings
    assert again.calls == (0, 0, 0)


async def test_a_trial_that_cannot_compile_is_reported_and_ranked_last() -> None:
    models = Models()

    def no_compile_model() -> FixtureChatModel:
        raise CompileModelUnavailable("no key")

    score = await score_matcher(
        _sample(),
        compile_model_factory=no_compile_model,
        parse_model_factory=lambda: models.parse,
        judge_model_factory=lambda: models.judge,
    )

    assert score.uncompiled == ["NCT01", "NCT02", "NCT03", "NCT04"]
    assert score.rankings[2] == ["NCT01", "NCT02", "NCT04"]
    assert "compile_rate" not in score.metrics
