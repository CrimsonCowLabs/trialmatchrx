"""One match run (SPEC.md pipeline 4): parse -> search cached trials -> compile -> evaluate -> rank.

    result = await run_match(rec, req)              # {"patient": ..., "matches": [...]}

The router runs this as a background traced run. Trace shape:
run > parse_patient, search_trials, trial:<nct> (> compile_criteria ..., rule:<nct>:<id> ...),
rank. A trial whose criteria can't be compiled (cache miss with no API key, malformed model
output) is dropped from the results with a failed `trial:<nct>` step; the run carries on.
"""

import asyncio
from typing import Any

from app.config import get_settings
from app.pipeline.compile_criteria import (
    CompileFailed,
    CompileModelUnavailable,
    ModelFactory,
    anthropic_compile_model,
    compile_study,
)
from app.pipeline.evaluate import Judge, evaluate_trial, no_judge
from app.pipeline.rank import build_match, rank_matches
from app.pipeline.trial_search import CandidateTrial, search_cached_trials
from app.schemas import MatchRequest, PatientFacts, TrialMatch
from app.sources import ctgov
from app.stub_data import STUB_PATIENT
from app.trace.recorder import TraceRecorder, describe_error

# SPEC.md: Semaphore(8). This bounds trials in flight; a judge that calls an LLM per criterion
# must use its own semaphore (sharing this one would deadlock: each trial holds a slot).
TRIAL_CONCURRENCY = 8


async def _parse_patient(rec: TraceRecorder, note: str) -> PatientFacts:
    # HACK(demo): swap for app.pipeline.parse_patient.parse_patient once #4 merges. Until then
    # every note yields the SPEC demo patient (61M, T2D, HbA1c 8.4%, eGFR 48, metformin).
    async with rec.step("parse_patient", "step", {"note_chars": len(note)}) as s:
        facts = STUB_PATIENT.model_copy(deep=True)
        s.output = {"patient": facts.model_dump(mode="json")}
        s.note = "demo patient facts (stub: the note parser lands in #4)"
    return facts


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
    judge: Judge = no_judge,
) -> dict[str, Any]:
    """The whole match. Returns the run result stored on the run row (read back by
    `GET /api/runs/{run_id}`): `{"patient": PatientFacts, "matches": list[TrialMatch]}`."""
    facts = await _parse_patient(rec, req.note or "")
    trials = await search_cached_trials(
        rec,
        _origin(facts),
        radius_mi=req.radius_mi,
        limit=get_settings().match_max_trials,
        condition=req.condition,
    )

    slots = asyncio.Semaphore(TRIAL_CONCURRENCY)

    async def bounded(trial: CandidateTrial) -> TrialMatch | None:
        async with slots:
            return await match_trial(rec, trial, facts, model_factory=model_factory, judge=judge)

    results = await asyncio.gather(*(bounded(t) for t in trials))
    matches = [m for m in results if m is not None]

    async with rec.step("rank", "step", {"trials": len(matches)}) as s:
        ranked = rank_matches(matches)
        tiers = {
            t: sum(m.tier == t for m in ranked) for t in ("likely", "needs_info", "ineligible")
        }
        s.output = {"tiers": tiers, "order": [m.nct_id for m in ranked]}
        s.note = (
            f"{tiers['likely']} likely, {tiers['needs_info']} needs info, "
            f"{tiers['ineligible']} ineligible"
        )

    return {
        "patient": facts.model_dump(mode="json"),
        "matches": [m.model_dump(mode="json") for m in ranked],
    }
