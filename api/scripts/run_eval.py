"""Score the matcher and BM25 on the fixed TREC sample and write an `eval_runs` row for each.

    make eval                                   # or: cd api && uv run python -m scripts.run_eval
    uv run python -m scripts.run_eval --rebuild # redraw + refetch the sample (network)
    uv run python -m scripts.run_eval --bm25-only

The matcher runs the full pipeline (parse -> compile -> evaluate -> judge -> verify -> rank) on
each topic as a traced match run, so it needs ANTHROPIC_API_KEY. The first run is slow and
costs tokens; criteria land in the compile cache and every parse / judge answer in `llm_cache`,
so a re-run on the same sample replays them and scores the same. Without a key the matcher is
skipped (BM25 still runs). An incomplete matcher run (a trial failed to compile, or a judge call
errored) is printed but not recorded and exits 1: failures aren't cached, so it wouldn't
reproduce. Re-run to retry just those; the history only holds complete, replayable scores.

The first run builds the sample (network): downloads the TREC 2021 topics + qrels into
data/trec/, draws 15 topics x 20 judged trials, fetches each trial from ClinicalTrials.gov and
saves data/fixtures/trec/sample.json. Every later run reads that file and never touches the
network.
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


def _score_matcher(sample: trec.TrecSample, git_sha: str | None) -> MatcherScore:
    """Score the matcher; record it only when complete (a re-run would replay every answer)."""
    print(f"matcher: {len(sample.topics)} topics, one traced match run each ...")
    score = asyncio.run(score_matcher(sample))
    if score.complete:
        row = record_eval_run(MATCHER, score.metrics, sample=sample, git_sha=git_sha)
        print(f"matcher: eval_runs {row.id[:8]}, git {row.git_sha}")
    else:
        print(
            f"matcher: incomplete, NOT recorded: {len(score.uncompiled)} trials could not be "
            f"compiled ({', '.join(score.uncompiled) or 'none'}), {score.judge_errors} judge "
            "calls failed. Re-run to retry them (everything else replays from the cache)."
        )
    return score


def main(rebuild: bool, bm25_only: bool) -> None:
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
    bm25 = score_bm25(sample)
    bm25_row = record_eval_run(BM25, bm25, sample=sample, git_sha=git_sha)
    print(f"bm25: eval_runs {bm25_row.id[:8]}, git {bm25_row.git_sha}")

    score: MatcherScore | None = None
    if bm25_only:
        print("matcher: skipped (--bm25-only)")
    elif not get_settings().anthropic_api_key:
        print("matcher: skipped, ANTHROPIC_API_KEY is not set (it parses and judges with the LLM)")
    else:
        score = _score_matcher(sample, git_sha)

    _report(score.metrics if score else None, bm25)
    print(f"prompts: {bm25_row.prompt_version}")
    if score is not None and not score.complete:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="redraw and refetch the sample")
    parser.add_argument("--bm25-only", action="store_true", help="skip the matcher (no LLM)")
    args = parser.parse_args()
    main(args.rebuild, args.bm25_only)
