"""The full matcher scored on the fixed TREC sample (SPEC.md "7. Eval harness", issue #11).

    score = await score_matcher(sample)        # real models, answers cached in `llm_cache`
    score.metrics                              # ndcg@10, p@10, accuracy, compile_rate

Each topic is one traced `match` run (`/runs/<id>` shows it): the topic text is the note, so it
goes through parse -> compile -> evaluate -> judge -> verify -> rank exactly as a live match does,
except that the candidates are the topic's own judged trials (no site search, no distance).

- Ranking: `rank.rank_matches` (tier, then fewer unknowns, then NCT ID). A trial whose
  criteria can't be compiled has no verdicts, so it goes last (NCT order) and is reported in
  `uncompiled`; it counts as called eligible, since nothing excluded the patient.
- Accuracy: a trial is called eligible unless its tier is `ineligible` (a criterion failed).
- Compile rate: criteria with a predicate over all criteria, pooled over the sample's trials
  (each trial counted once), from the compile cache.

Reproducible on a warm cache: compiled criteria come from `compiled_criteria`, and every parse
and judge answer from `llm_cache` (`app/eval/llm_cache.py`), so a re-run calls no model.
"""

import asyncio
from dataclasses import dataclass

from langchain_core.caches import BaseCache

from app.eval.llm_cache import SqliteLlmCache, with_cache
from app.eval.runs import COMPILE_RATE, score_rankings, topic_labels
from app.pipeline import criteria_cache
from app.pipeline.compile_criteria import PROMPT_NAME as COMPILE_PROMPT
from app.pipeline.compile_criteria import ModelFactory, anthropic_compile_model
from app.pipeline.judge import anthropic_judge_model
from app.pipeline.match_run import TRIAL_CONCURRENCY, judges_for_run, match_trial
from app.pipeline.parse_patient import anthropic_parse_model, parse_patient
from app.pipeline.rank import TIER_ORDER, rank_matches
from app.pipeline.trial_search import CandidateTrial
from app.prompts import load_prompt
from app.schemas import TrialMatch
from app.sources import ctgov
from app.sources.trec import Topic, TrecSample
from app.trace.runner import traced_run


@dataclass
class MatcherScore:
    metrics: dict[str, float]  # ndcg@10, p@10, accuracy, compile_rate (when anything compiled)
    rankings: dict[int, list[str]]  # topic id -> its judged trials, best first
    uncompiled: list[str]  # NCT IDs whose criteria couldn't be compiled
    run_ids: dict[int, str]  # topic id -> its traced match run


@dataclass
class _TopicResult:
    run_id: str
    ranking: list[str]
    called_eligible: dict[str, bool]
    uncompiled: list[str]


def _candidate(nct: str, sample: TrecSample) -> CandidateTrial:
    study = sample.trials[nct]
    summary = ctgov.summarize(study)
    return CandidateTrial(nct, summary.title, summary.phase, None, study)


async def _match_topic(
    topic: Topic,
    sample: TrecSample,
    *,
    compile_model_factory: ModelFactory,
    parse_model_factory: ModelFactory,
    judge_model_factory: ModelFactory,
) -> _TopicResult:
    ncts = sorted(topic_labels(sample, topic.id))
    request = {"note": topic.text, "eval": {"topic": topic.id}}
    async with traced_run("match", request) as run:
        rec = run.recorder
        facts = await parse_patient(rec, topic.text, model_factory=parse_model_factory)
        judge_for = judges_for_run(rec, judge_model_factory, topic.text)
        slots = asyncio.Semaphore(TRIAL_CONCURRENCY)

        async def bounded(trial: CandidateTrial) -> TrialMatch | None:
            async with slots:
                return await match_trial(
                    rec, trial, facts, model_factory=compile_model_factory, judge=judge_for(trial)
                )

        results = await asyncio.gather(*(bounded(_candidate(n, sample)) for n in ncts))
        matches = [m for m in results if m is not None]
        uncompiled = [nct for nct, m in zip(ncts, results, strict=True) if m is None]

        async with rec.step("rank", "step", {"trials": len(matches)}) as s:
            ranked = rank_matches(matches)
            tiers = {t: sum(m.tier == t for m in ranked) for t in TIER_ORDER}
            s.output = {"tiers": tiers, "order": [m.nct_id for m in ranked]}
        run.result = {
            "patient": facts.model_dump(mode="json"),
            "matches": [m.model_dump(mode="json") for m in ranked],
        }

    called = {m.nct_id: m.tier != "ineligible" for m in matches} | dict.fromkeys(uncompiled, True)
    return _TopicResult(run.run_id, [m.nct_id for m in ranked] + uncompiled, called, uncompiled)


def compile_rate(sample: TrecSample, ncts: set[str]) -> float | None:
    """Pooled share of criteria with a predicate over `ncts`, from the compile cache."""
    version = load_prompt(COMPILE_PROMPT).version
    total = with_predicate = 0
    for nct in sorted(ncts):
        eligibility = sample.trials[nct]["protocolSection"].get("eligibilityModule", {})
        criteria = criteria_cache.get(nct, criteria_cache.eligibility_hash(eligibility), version)
        for c in criteria or []:
            total += 1
            with_predicate += c.predicate is not None
    return with_predicate / total if total else None


async def score_matcher(
    sample: TrecSample,
    *,
    compile_model_factory: ModelFactory = anthropic_compile_model,
    parse_model_factory: ModelFactory = anthropic_parse_model,
    judge_model_factory: ModelFactory = anthropic_judge_model,
    llm_cache: BaseCache | None = None,
) -> MatcherScore:
    """Run the matcher on every topic of the sample (one topic at a time) and score it.
    Parse and judge answers go through `llm_cache` (default: the `llm_cache` table)."""
    cache = llm_cache or SqliteLlmCache()
    rankings: dict[int, list[str]] = {}
    called: dict[tuple[int, str], bool] = {}
    run_ids: dict[int, str] = {}
    uncompiled: set[str] = set()
    for topic in sample.topics:
        result = await _match_topic(
            topic,
            sample,
            compile_model_factory=compile_model_factory,
            parse_model_factory=with_cache(parse_model_factory, cache),
            judge_model_factory=with_cache(judge_model_factory, cache),
        )
        rankings[topic.id] = result.ranking
        run_ids[topic.id] = result.run_id
        uncompiled.update(result.uncompiled)
        called |= {(topic.id, nct): ok for nct, ok in result.called_eligible.items()}

    metrics = score_rankings(sample, rankings, lambda topic_id, nct: called[(topic_id, nct)])
    rate = compile_rate(sample, {j.nct_id for j in sample.judgments} - uncompiled)
    if rate is not None:
        metrics[COMPILE_RATE] = rate
    return MatcherScore(metrics, rankings, sorted(uncompiled), run_ids)
