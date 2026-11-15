"""The full matcher scored on the fixed TREC sample (SPEC.md "7. Eval harness", issue #11).

    score = await score_matcher(sample)        # real models, answers cached in `llm_cache`
    score.metrics                              # ndcg@10, p@10, accuracy, compile_rate
    score.complete                             # False: some trial or judge call failed

Each topic is one traced `match` run (`/runs/<id>` shows it): the topic text is the note, so it
goes through parse -> compile -> evaluate -> judge -> verify -> rank exactly as a live match does
(`match_run.match_trials` + `rank_step`), except that the candidates are the topic's own judged
trials (no site search, no distance).

- Ranking: `rank.rank_matches` (tier, then fewer unknowns, then NCT ID). A trial whose
  criteria can't be compiled has no verdicts, so it goes last (NCT order) and is reported in
  `uncompiled`; it counts as called eligible, since nothing excluded the patient.
- Accuracy: a trial is called eligible unless its tier is `ineligible` (a criterion failed).
- Compile rate: criteria with a predicate over all criteria, pooled over the sample's trials
  (each trial counted once), from the compile cache.

Reproducible on a warm cache: compiled criteria come from `compiled_criteria`, and every parse
and judge answer from `llm_cache` (`app/eval/llm_cache.py`), so a complete re-run calls no
model. Failures are not cached (a compile that failed, a judge call that errored and fell back
to `unknown`, every answer of a topic whose match run failed), so a score with any of them is
not `complete`: a re-run would ask again.
A topic whose match run raises (a parse failure, or any other error) is reported in `failed` with
the step it broke and is left out of the metrics; the other topics are still matched.
"""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from langchain_core.caches import BaseCache

from app.eval.fail_fast import FailFastStop, FailFastWatch
from app.eval.llm_cache import PendingCache, SqliteLlmCache, with_cache
from app.eval.offline import (
    STEPS,
    CacheMisses,
    CacheOnly,
    Step,
    offline_compile_model,
    offline_judge_model,
    offline_parse_model,
)
from app.eval.runs import COMPILE_RATE, score_rankings, topic_labels
from app.pipeline import criteria_cache
from app.pipeline.compile_criteria import PROMPT_NAME as COMPILE_PROMPT
from app.pipeline.compile_criteria import ModelFactory, anthropic_compile_model
from app.pipeline.judge import STEP_PREFIX as JUDGE_STEP
from app.pipeline.judge import anthropic_judge_model
from app.pipeline.match_run import TRIAL_CONCURRENCY, match_trials, rank_step
from app.pipeline.parse_patient import anthropic_parse_model, parse_patient
from app.pipeline.trial_search import CandidateTrial
from app.prompts import load_prompt
from app.schemas import Criterion
from app.sources import ctgov
from app.sources.trec import Topic, TrecSample
from app.trace import store
from app.trace.bus import EventBus
from app.trace.bus import bus as default_bus
from app.trace.recorder import describe_error
from app.trace.runner import traced_run

# --fail-fast stops after which the stopped topic's answers are cached (see `score_matcher`)
KEEPS_ANSWERS = ("compile", "judge")


@dataclass
class TopicFailure:
    """A topic whose match run raised: it has no ranking, and the score is not complete."""

    topic_id: int
    run_id: str  # the failed match run
    step: str  # the steps the error failed, outermost first ("trial:NCT01 > compile_criteria")
    error: str  # `describe_error` of what was raised


@dataclass
class MatcherScore:
    metrics: dict[str, float]  # ndcg@10, p@10, accuracy, compile_rate (when anything compiled)
    rankings: dict[int, list[str]]  # topic id -> its judged trials, best first
    uncompiled: list[str]  # NCT IDs whose criteria couldn't be compiled
    judge_errors: int  # judge calls that errored (verdict fell back to unknown, not cached)
    run_ids: dict[int, str]  # topic id -> its traced match run
    failed: list[TopicFailure] = field(default_factory=list)  # topics whose match run raised
    # --offline: per step, the calls that missed the cache (would have gone to the API)
    cache_misses: dict[Step, int] = field(default_factory=dict)
    stopped: FailFastStop | None = None  # --fail-fast: the failure the eval stopped at

    @property
    def complete(self) -> bool:
        """Every topic matched, every trial compiled and every judge call answered (offline:
        from the cache), so a re-run replays it all."""
        return (
            not self.failed
            and not self.uncompiled
            and not self.judge_errors
            and not any(self.cache_misses.values())
            and self.stopped is None
        )


@dataclass
class _TopicResult:
    run_id: str
    ranking: list[str]
    called_eligible: dict[str, bool]
    uncompiled: list[str]
    judge_errors: int


def _candidate(nct: str, sample: TrecSample) -> CandidateTrial:
    study = sample.trials[nct]
    summary = ctgov.summarize(study)
    return CandidateTrial(nct, summary.title, summary.phase, None, study)


def _judge_errors(run_id: str) -> int:
    """`judge:<nct>:<id>:error` events: the judge's API call failed (see `judge.py`). Offline,
    this includes the cache misses; `score_matcher` takes those out (`CacheMisses`)."""
    return sum(
        e.kind == "error" and e.name.startswith(JUDGE_STEP) and e.name.endswith(":error")
        for e in store.latest_events(run_id)
    )


async def _match_topic(
    topic: Topic,
    sample: TrecSample,
    *,
    compile_model_factory: ModelFactory,
    parse_model_factory: ModelFactory,
    judge_model_factory: ModelFactory,
    bus: EventBus = default_bus,
    trial_concurrency: int = TRIAL_CONCURRENCY,
) -> _TopicResult | TopicFailure:
    """The topic's match run, or how it failed: any error fails this topic, not the eval.
    `bus` gets the run's trace events (`--fail-fast` watches them)."""
    ncts = sorted(topic_labels(sample, topic.id))
    request = {"note": topic.text, "eval": {"topic": topic.id}}
    run_id = store.create_run("match", request)
    try:
        async with traced_run("match", request, run_id=run_id, bus=bus) as run:
            facts = await parse_patient(run.recorder, topic.text, model_factory=parse_model_factory)
            results = await match_trials(
                run.recorder,
                [_candidate(n, sample) for n in ncts],
                facts,
                note=topic.text,
                model_factory=compile_model_factory,
                judge_model_factory=judge_model_factory,
                concurrency=trial_concurrency,
            )
            ranked = await rank_step(run.recorder, [m for m in results if m is not None])
            run.result = {
                "patient": facts.model_dump(mode="json"),
                "matches": [m.model_dump(mode="json") for m in ranked],
            }
    except Exception as exc:  # `traced_run` has marked the run failed
        error = describe_error(exc)
        return TopicFailure(topic.id, run_id, _failed_steps(run_id, error), error)

    uncompiled = [nct for nct, m in zip(ncts, results, strict=True) if m is None]
    called = {m.nct_id: m.tier != "ineligible" for m in ranked} | dict.fromkeys(uncompiled, True)
    return _TopicResult(
        run.run_id,
        [m.nct_id for m in ranked] + uncompiled,
        called,
        uncompiled,
        _judge_errors(run.run_id),
    )


def _failed_steps(run_id: str, error: str) -> str:
    """Where `error` broke the run: the steps it failed on its way out, outermost first, or
    `match` when it was raised outside any step. Each level takes the step that closed last
    (the error closes its steps after any handled failure), so a trial that failed earlier and
    was handled, even with the same error, is left out."""
    failed = [
        e
        for e in store.latest_events(run_id)
        if e.kind == "step" and e.status == "failed" and (e.output or {}).get("error") == error
    ]
    path: list[str] = []
    parent: str | None = None
    while step := max(
        (e for e in failed if e.parent_id == parent), key=lambda e: e.seq, default=None
    ):
        path.append(step.name)
        parent = step.id
    return " > ".join(path) or "match"


def _cached_criteria(sample: TrecSample, nct: str) -> list[Criterion] | None:
    eligibility = sample.trials[nct]["protocolSection"].get("eligibilityModule", {})
    version = load_prompt(COMPILE_PROMPT).version
    return criteria_cache.get(nct, criteria_cache.eligibility_hash(eligibility), version)


def _not_compiled(sample: TrecSample) -> set[str]:
    """The sample's judged trials that are not in the compile cache."""
    return {j.nct_id for j in sample.judgments if _cached_criteria(sample, j.nct_id) is None}


def compile_rate(sample: TrecSample, ncts: set[str]) -> float | None:
    """Pooled share of criteria with a predicate over `ncts`, from the compile cache."""
    total = with_predicate = 0
    for nct in sorted(ncts):
        for c in _cached_criteria(sample, nct) or []:
            total += 1
            with_predicate += c.predicate is not None
    return with_predicate / total if total else None


async def score_matcher(
    sample: TrecSample,
    *,
    compile_model_factory: ModelFactory | None = None,
    parse_model_factory: ModelFactory | None = None,
    judge_model_factory: ModelFactory | None = None,
    llm_cache: BaseCache | None = None,
    offline: bool = False,
    fail_fast: bool = False,
) -> MatcherScore:
    """Run the matcher on every topic of the sample (one topic at a time) and score it.
    Parse and judge answers go through `llm_cache` (default: the `llm_cache` table). The model
    factories default to the live Anthropic models.

    `offline`: answer from the caches only (`app/eval/offline.py`). The compile model is never
    built (a compile-cache miss leaves the trial uncompiled); parse and judge models are built
    (offline defaults: the live models with a placeholder key) only to key the cache, and a miss
    raises `NotCached` before any request. `cache_misses` counts the misses per step.

    `fail_fast`: stop at the first model failure (`app/eval/fail_fast.py`): a failed parse,
    a trial that can't compile, a judge error or malformed answer, or (offline) a cache miss.
    Trials then run one at a time, so none starts after the failure, and no later topic runs.
    `stopped` says where it broke. The stopped topic's answers so far are cached when it stopped
    at a compile or judge failure (without the flag the topic would finish and cache them), not
    when its parse failed (#59: that answer may be the bad one)."""
    cache = llm_cache or SqliteLlmCache()
    misses = CacheMisses()
    if offline:
        compile_model_factory = offline_compile_model
        parse_model_factory = parse_model_factory or offline_parse_model
        judge_model_factory = judge_model_factory or offline_judge_model
    compile_factory = compile_model_factory or anthropic_compile_model
    parse_factory = parse_model_factory or anthropic_parse_model
    judge_factory = judge_model_factory or anthropic_judge_model
    rankings: dict[int, list[str]] = {}
    called: dict[tuple[int, str], bool] = {}
    run_ids: dict[int, str] = {}
    uncompiled: set[str] = set()
    judge_errors = 0
    failed: list[TopicFailure] = []
    stopped: FailFastStop | None = None
    for topic in sample.topics:
        pending = PendingCache(cache)  # a failed topic's answers are dropped, not cached
        parse_cache: BaseCache = pending
        judge_cache: BaseCache = pending
        if offline:  # a miss raises (nothing is pending, so the commit below writes nothing)
            parse_cache = CacheOnly(pending, "parse", misses)
            judge_cache = CacheOnly(pending, "judge", misses)
        watch = FailFastWatch(topic.id) if fail_fast else None
        judge_misses = len(misses.keys["judge"])
        match = _match_topic(
            topic,
            sample,
            compile_model_factory=compile_factory,
            parse_model_factory=with_cache(parse_factory, parse_cache),
            judge_model_factory=with_cache(judge_factory, judge_cache),
            bus=watch or default_bus,
            trial_concurrency=1 if fail_fast else TRIAL_CONCURRENCY,
        )
        result = await (match if watch is None else _until_failure(match, watch))
        if isinstance(result, FailFastStop):  # no later topic runs
            stopped = result
            run_ids[topic.id] = stopped.run_id
            # The cause, not the cancel; and failed even if the run got to finish first.
            store.finish_run(stopped.run_id, "failed", error=stopped.error)
            if stopped.step in KEEPS_ANSWERS:
                pending.commit()
            break
        run_ids[topic.id] = result.run_id
        if isinstance(result, TopicFailure):
            failed.append(result)
            continue
        pending.commit()
        rankings[topic.id] = result.ranking
        uncompiled.update(result.uncompiled)
        # an offline judge miss is an error event too; it is counted as a miss instead
        judge_errors += result.judge_errors - (len(misses.keys["judge"]) - judge_misses)
        called |= {(topic.id, nct): ok for nct, ok in result.called_eligible.items()}

    # Failed topics have no ranking: the metrics are over the matched topics only.
    matched = sample.model_copy(update={"topics": [t for t in sample.topics if t.id in rankings]})
    metrics: dict[str, float] = {}
    if matched.topics:
        metrics = score_rankings(matched, rankings, lambda topic_id, nct: called[(topic_id, nct)])
    ncts = {j.nct_id for j in matched.judgments if j.topic_id in rankings} - uncompiled
    rate = compile_rate(matched, ncts)
    if rate is not None:
        metrics[COMPILE_RATE] = rate
    cache_misses: dict[Step, int] = {}
    if offline:  # compile misses straight from the compile cache, reached by a topic or not
        cache_misses = misses.counts() | {"compile": len(_not_compiled(sample))}
        cache_misses = {step: cache_misses[step] for step in STEPS}
    return MatcherScore(
        metrics, rankings, sorted(uncompiled), judge_errors, run_ids, failed, cache_misses, stopped
    )


async def _until_failure[T](
    match: Coroutine[Any, Any, T], watch: FailFastWatch
) -> T | FailFastStop:
    """`match`, run as a task that `watch` cancels at the first failure, or that failure."""
    task = asyncio.create_task(match)
    watch.watch(task)
    try:
        result = await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if watch.failure is None or (current is not None and current.cancelling()):
            raise  # cancelled from outside (Ctrl-C), not by the watch
    return watch.failure or result
