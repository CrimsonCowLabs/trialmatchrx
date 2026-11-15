"""Score the matcher and BM25 on the fixed TREC sample and write an `eval_runs` row for each.

    make eval                                   # or: cd api && uv run python -m scripts.run_eval
    uv run python -m scripts.run_eval --rebuild # redraw + refetch the sample (network)
    uv run python -m scripts.run_eval --bm25-only
    uv run python -m scripts.run_eval --topics 2  # partial: first 2 topics only, not recorded
    uv run python -m scripts.run_eval --offline   # from the caches only: no API calls, no key
    uv run python -m scripts.run_eval --fail-fast # stop at the first model failure

The matcher runs the full pipeline (parse -> compile -> evaluate -> judge -> verify -> rank) on
each topic as a traced match run, so it needs ANTHROPIC_API_KEY. The first run is slow and
costs tokens; criteria land in the compile cache and every parse / judge answer in `llm_cache`,
so a re-run on the same sample replays them and scores the same. Without a key the matcher is
skipped (BM25 still runs). An incomplete matcher run (a topic's match run failed, a trial
failed to compile, or a judge call errored) is printed but not recorded and exits 1: failures
aren't cached, so it wouldn't reproduce. Re-run to retry just those; the history only holds
complete, replayable scores.

The first run builds the sample (network): downloads the TREC 2021 topics + qrels into
data/trec/, draws 15 topics x 20 judged trials, fetches each trial from ClinicalTrials.gov and
saves data/fixtures/trec/sample.json. Every later run reads that file and never touches the
network.

`--topics N` scores the matcher and BM25 on only the first N topics of the sample (sample order),
so only their judged trials (about 20 each) are compiled and judged: a bounded-cost live check
after a pipeline change. A partial score can't be compared with a full one, so it is labelled
partial and never written to `eval_runs`, even when complete, and even when N is every topic.
Its answers still land in the compile cache and `llm_cache`, so a later full run replays them.
N must be between 1 and the sample's topic count.

`--offline` scores the matcher from the caches only, so a change can be checked without spending
tokens. Every parse, compile and judge answer must come from the compile cache or `llm_cache`;
an uncached one fails at once with a "not cached" error and never reaches the API (the parse
and judge models are built with a placeholder key, which isn't part of the cache key, so no
ANTHROPIC_API_KEY is needed). The report prints, per step (parse / compile / judge), how many
calls missed the cache and would have gone to the API. Compile misses are every judged trial
not in the compile cache; a topic whose parse missed is not matched, so its judge calls (which
depend on the parsed facts) are not counted. A fully cached offline run scores the
same as a live re-run and is recorded the same way; an incomplete one prints the score over what
replayed, records nothing (BM25 included) and exits 1.

`--fail-fast` stops at the first model failure: a failed parse, a trial whose criteria can't be
compiled, a judge call that errored or answered malformed twice, or (with `--offline`) a cache
miss. Trials then run one at a time, so no later trial starts after the failure. It prints the
step, topic, trial (if any) and error, records nothing (BM25 included) and exits 1. Answers the
stopped topic already got stay cached unless its parse failed. Without it,
failures are collected per topic as above. The flags combine: `--offline --fail-fast` stops at
the first cache miss.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import init_db
from app.eval.matcher import MatcherScore, score_matcher
from app.eval.runs import (
    ACCURACY,
    BM25,
    COMPILE_RATE,
    MATCHER,
    K,
    current_git_sha,
    current_prompt_version,
    record_eval_run,
    score_bm25,
)
from app.sources import ctgov, trec


async def _download(client: httpx.AsyncClient, url: str) -> str:
    """The file at `url`, from data/trec/ when already downloaded."""
    path = trec.RAW_DIR / Path(url).name
    if not path.exists():
        resp = (await client.get(url, follow_redirects=True)).raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text)
    return path.read_text()


async def build() -> trec.TrecSample:
    async with httpx.AsyncClient(timeout=60.0) as client:
        topics = trec.parse_topics(await _download(client, trec.TOPICS_URL))
        qrels = trec.parse_qrels(await _download(client, trec.QRELS_URL))
    print(f"trec: {len(topics)} topics, {len(qrels)} qrels")
    async with ctgov.make_client() as client:
        sample = await trec.build_sample(topics, qrels, client=client)
    trec.save_sample(sample)
    drawn = sample.n_topics * sample.per_topic
    print(
        f"sample: drew {drawn} judged trials over {sample.n_topics} topics (seed "
        f"{sample.seed}); dropped {len(sample.dropped)} trials ({drawn - sample.sample_size} "
        f"judgments): {_reasons(sample)}; saved {trec.SAMPLE_PATH}"
    )
    return sample


def _reasons(sample: trec.TrecSample) -> str:
    counts: dict[str, int] = {}
    for reason in sample.dropped.values():
        key = "merged into another record" if reason.startswith("merged into") else reason
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{n} {reason}" for reason, n in sorted(counts.items())) or "none"


COLUMNS = ((f"ndcg@{K}", f"nDCG@{K}"), (f"p@{K}", f"P@{K}"), (ACCURACY, "accuracy"))


def _row(system: str, metrics: dict[str, float]) -> str:
    cells = (f"{metrics[k]:>9.4f}" if k in metrics else f"{'-':>9}" for k, _ in COLUMNS)
    return f"{system:<8} " + " ".join(cells)


def _report(matcher: dict[str, float] | None, bm25: dict[str, float]) -> None:
    """The side-by-side table, then the compile rate and the matcher's lift over BM25."""
    print()
    print(f"{'system':<8} " + " ".join(f"{label:>9}" for _, label in COLUMNS))
    if matcher is not None:
        print(_row(MATCHER, matcher))
    print(_row(BM25, bm25))
    if matcher is None:
        return
    rate = matcher.get(COMPILE_RATE)
    print(f"compile rate: {rate:.1%}" if rate is not None else "compile rate: -")
    both = [(k, label) for k, label in COLUMNS if k in matcher and k in bm25]
    print("matcher vs BM25: " + "  ".join(f"{lb} {matcher[k] - bm25[k]:+.4f}" for k, lb in both))


def _partial_label(sample: trec.TrecSample) -> str:
    return f"partial run: {len(sample.topics)} of {sample.n_topics} topics"


def _score_matcher(
    sample: trec.TrecSample,
    git_sha: str | None,
    *,
    partial: bool,
    offline: bool = False,
    fail_fast: bool = False,
) -> MatcherScore:
    """Score the matcher; record it only when complete (a re-run would replay every answer)
    and not a --topics run. `offline`: from the caches only (no API calls). `fail_fast`: stop
    at the first model failure and record nothing."""
    mode = ", offline (caches only, no API calls)" if offline else ""
    print(f"matcher: {len(sample.topics)} topics, one traced match run each{mode} ...")
    score = asyncio.run(score_matcher(sample, offline=offline, fail_fast=fail_fast))
    if (stop := score.stopped) is not None:
        trial = f", trial {stop.nct_id}" if stop.nct_id else ""
        error = stop.error.splitlines()[0]
        print(
            f"matcher: stopped (--fail-fast) at {stop.step}, topic {stop.topic_id}{trial}: "
            f"{error} (run {stop.run_id}); NOT recorded"
        )
        return score
    if offline:
        misses = ", ".join(f"{step} {n}" for step, n in score.cache_misses.items())
        print(f"matcher: offline, cache misses (would call the API): {misses}")
    if score.complete and partial:
        print(f"matcher: {_partial_label(sample)}, NOT recorded")
    elif score.complete:
        row = record_eval_run(MATCHER, score.metrics, sample=sample, git_sha=git_sha)
        print(f"matcher: eval_runs {row.id[:8]}, git {row.git_sha}")
    else:
        print(
            f"matcher: incomplete, NOT recorded: {len(score.failed)} topics failed, "
            f"{len(score.uncompiled)} trials could not be compiled "
            f"({', '.join(score.uncompiled) or 'none'}), {score.judge_errors} judge calls "
            "failed. "
            + (
                "Run without --offline to fill the cache."
                if offline
                else "Re-run to retry them (everything else replays from the cache)."
            )
        )
        for f in score.failed:  # the first line of the error; the run's trace has the rest
            error = f.error.splitlines()[0]
            print(f"  topic {f.topic_id} failed at {f.step}: {error} (run {f.run_id})")
    return score


def _record_bm25(bm25: dict[str, float], sample: trec.TrecSample, git_sha: str | None) -> None:
    row = record_eval_run(BM25, bm25, sample=sample, git_sha=git_sha)
    print(f"bm25: eval_runs {row.id[:8]}, git {row.git_sha}")


def _topic_count(value: str) -> int:
    """--topics N: at least 1, checked before a --rebuild fetches anything (the upper bound
    needs the sample, see `trec.first_topics`)."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {value!r}") from None
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {n}")
    return n


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="redraw and refetch the sample")
    parser.add_argument("--bm25-only", action="store_true", help="skip the matcher (no LLM)")
    parser.add_argument(
        "--topics",
        type=_topic_count,
        metavar="N",
        help="score only the first N topics (partial run, never recorded)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="score the matcher from the caches only: no API calls, no API key needed",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop at the first model failure (or --offline cache miss); record nothing",
    )
    return parser.parse_args(argv)


def main(
    rebuild: bool,
    bm25_only: bool,
    topics: int | None = None,
    *,
    offline: bool = False,
    fail_fast: bool = False,
) -> None:
    """`topics`: score only the first N topics; such a run is partial and never recorded, even
    when N is every topic of the sample (issue #61). `offline`: the matcher answers from the
    caches only; `fail_fast`: it stops at the first failure (issue #60). With either, BM25 is
    recorded only alongside a recorded matcher run, so a failed check records nothing."""
    partial = topics is not None
    runs_matcher = not bm25_only and (offline or bool(get_settings().anthropic_api_key))
    defer_bm25 = runs_matcher and (offline or fail_fast)
    init_db()
    git_sha = current_git_sha()  # before a first run writes sample.json into the tree
    if rebuild or not trec.SAMPLE_PATH.exists():
        sample = asyncio.run(build())
    else:
        sample = trec.load_sample()
    print(
        f"sample: {sample.sample_size} judged (topic, trial) pairs, {len(sample.trials)} trials, "
        f"{len(sample.topics)} topics; {len(sample.dropped)} trials dropped ({_reasons(sample)})"
    )
    if topics is not None:
        try:
            sample = trec.first_topics(sample, topics)
        except ValueError as e:
            sys.exit(f"run_eval: --topics {e}")
    bm25 = score_bm25(sample)
    if partial:
        print(f"bm25: {_partial_label(sample)}, NOT recorded")
    elif not defer_bm25:
        _record_bm25(bm25, sample, git_sha)

    score: MatcherScore | None = None
    if bm25_only:
        print("matcher: skipped (--bm25-only)")
    elif not runs_matcher:
        print("matcher: skipped, ANTHROPIC_API_KEY is not set (it parses and judges with the LLM)")
    else:
        score = _score_matcher(
            sample, git_sha, partial=partial, offline=offline, fail_fast=fail_fast
        )
    if defer_bm25 and not partial:
        if score is not None and score.complete:
            _record_bm25(bm25, sample, git_sha)
        else:
            print("bm25: NOT recorded (the matcher run was not recorded)")

    if partial:
        print(
            f"\n{_partial_label(sample)}: metrics over those topics only, "
            "not comparable with a full run"
        )
    _report(score.metrics if score and not score.stopped else None, bm25)  # no half score
    print(f"prompts: {current_prompt_version()}")
    if score is not None and not score.complete:
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    main(args.rebuild, args.bm25_only, args.topics, offline=args.offline, fail_fast=args.fail_fast)
