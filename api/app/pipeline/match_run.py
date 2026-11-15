"""One match run (SPEC.md pipeline 4): parse -> search cached trials -> compile -> evaluate -> rank.

    result = await run_match(rec, req)              # {"patient": ..., "matches": [...]}

The router runs this as a background traced run. Trace shape:
run > parse_patient, search_trials, trial:<nct> (> compile_criteria ..., rule:<nct>:<id> ...,
judge:<nct>:<id> ...), rank. A trial whose criteria can't be compiled (cache miss with no API
key, malformed model output) is dropped from the results with a failed `trial:<nct>` step; the
run carries on.

Criteria with no predicate go to the LLM judge (`judge.llm_judge`), bounded by one judge
semaphore shared by every trial in the run. With no API key for the judge they stay `unknown`
(`evaluate.no_judge`) and a skipped `judge` event says why; the run still finishes.
"""

import asyncio
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.pipeline.compile_criteria import (
    CompileFailed,
    CompileModelUnavailable,
    ModelFactory,
    anthropic_compile_model,
    clean_eligibility_text,
    compile_study,
)
from app.pipeline.evaluate import Judge, evaluate_trial, no_judge
from app.pipeline.judge import (
    JudgeModelUnavailable,
    anthropic_judge_model,
    llm_judge,
    new_judge_semaphore,
)
from app.pipeline.parse_patient import anthropic_parse_model, parse_patient
from app.pipeline.rank import TIER_ORDER, build_match, rank_matches
from app.pipeline.trial_search import CandidateTrial, search_cached_trials
from app.schemas import MatchRequest, PatientFacts, TrialMatch
from app.sources import ctgov
from app.stub_data import STUB_PATIENT
from app.trace.recorder import TraceRecorder, describe_error

# SPEC.md: Semaphore(8). This bounds trials in flight; a judge that calls an LLM per criterion
# must use its own semaphore (sharing this one would deadlock: each trial holds a slot).
TRIAL_CONCURRENCY = 8


async def _parse_patient(
    rec: TraceRecorder, req: MatchRequest, parse_model_factory: ModelFactory
) -> PatientFacts:
    if req.note:
        return await parse_patient(rec, req.note, model_factory=parse_model_factory)
    # HACK(demo): stub — the FHIR path (sources/synthea.py) doesn't exist yet.
    async with rec.step("parse_patient", "step", {"fhir_bundle": True}) as s:
        facts = STUB_PATIENT.model_copy(deep=True)
        s.output = {"patient": facts.model_dump(mode="json")}
        s.note = "FHIR bundle parsing not implemented; stub patient (stub)"
    return facts


def _trial_text(study: dict[str, Any]) -> str:
    eligibility = study["protocolSection"].get("eligibilityModule", {})
    return clean_eligibility_text(eligibility.get("eligibilityCriteria") or "")


def _judges(
    rec: TraceRecorder, judge_model_factory: ModelFactory, note: str | None
) -> Callable[[CandidateTrial], Judge]:
    """How each trial gets its judge: one model and one semaphore for the whole run."""
    try:
        model = judge_model_factory()
    except JudgeModelUnavailable as exc:
        rec.event(
            "judge",
            "step",
            status="skipped",
            output={"error": describe_error(exc)},
            note="no judge model: criteria without a rule stay unknown",
        )
        return lambda trial: no_judge
    semaphore = new_judge_semaphore()
    return lambda trial: llm_judge(
        model, trial_text=_trial_text(trial.study), note=note, semaphore=semaphore
    )


def _origin(facts: PatientFacts) -> tuple[float, float]:
    if facts.lat is not None and facts.lon is not None:
        return facts.lat, facts.lon
    return ctgov.SACRAMENTO


async def match_trial(
    rec: TraceRecorder,
    trial: CandidateTrial,
    facts: PatientFacts,
    *,
    model_factory: ModelFactory = anthropic_compile_model,
    judge: Judge = no_judge,
) -> TrialMatch | None:
    """Compile (cached) and evaluate one trial inside a `trial:<nct>` step. None if the trial's
    criteria can't be compiled."""
    step_input = {"nct": trial.nct_id, "distance_mi": trial.distance_mi}
    async with rec.step(f"trial:{trial.nct_id}", "step", step_input) as s:
        try:
            criteria = await compile_study(trial.study, rec, model_factory=model_factory)
        except (CompileModelUnavailable, CompileFailed) as exc:
            s.status = "failed"
            s.output = {"error": describe_error(exc)}
            s.note = f"{trial.nct_id} skipped: criteria could not be compiled"
            return None
        verdicts = await evaluate_trial(trial.nct_id, criteria, facts, rec, judge=judge)
        match = build_match(trial.nct_id, trial.title, trial.phase, trial.distance_mi, verdicts)
        s.output = {"tier": match.tier, "counts": match.counts}
        s.note = f"{trial.nct_id}: {match.tier} ({_counts_text(match.counts)})"
    return match


def _counts_text(counts: dict[str, int]) -> str:
    return " / ".join(f"{counts.get(k, 0)} {k}" for k in ("pass", "fail", "unknown"))


async def run_match(
    rec: TraceRecorder,
    req: MatchRequest,
    *,
    model_factory: ModelFactory = anthropic_compile_model,
    parse_model_factory: ModelFactory = anthropic_parse_model,
    judge_model_factory: ModelFactory = anthropic_judge_model,
) -> dict[str, Any]:
    """The whole match. Returns the run result stored on the run row (read back by
    `GET /api/runs/{run_id}`): `{"patient": PatientFacts, "matches": list[TrialMatch]}`.
    `model_factory` builds the compile model (only on a cache miss), `parse_model_factory` the
    note-parse model, `judge_model_factory` the judge model (once per run)."""
    facts = await _parse_patient(rec, req, parse_model_factory)
    trials = await search_cached_trials(
        rec,
        _origin(facts),
        radius_mi=req.radius_mi,
        limit=get_settings().match_max_trials,
        condition=req.condition,
    )

    judge_for = _judges(rec, judge_model_factory, req.note)
    slots = asyncio.Semaphore(TRIAL_CONCURRENCY)

    async def bounded(trial: CandidateTrial) -> TrialMatch | None:
        async with slots:
            return await match_trial(
                rec, trial, facts, model_factory=model_factory, judge=judge_for(trial)
            )

    results = await asyncio.gather(*(bounded(t) for t in trials))
    matches = [m for m in results if m is not None]

    async with rec.step("rank", "step", {"trials": len(matches)}) as s:
        ranked = rank_matches(matches)
        tiers = {t: sum(m.tier == t for m in ranked) for t in TIER_ORDER}
        s.output = {"tiers": tiers, "order": [m.nct_id for m in ranked]}
        s.note = (
            f"{tiers['likely']} likely, {tiers['needs_info']} needs info, "
            f"{tiers['ineligible']} ineligible"
        )

    return {
        "patient": facts.model_dump(mode="json"),
        "matches": [m.model_dump(mode="json") for m in ranked],
    }
