"""Score BM25 on the fixed TREC sample and write an `eval_runs` row.

    make eval                                   # or: cd api && uv run python -m scripts.run_eval
    uv run python -m scripts.run_eval --rebuild # redraw + refetch the sample (network)

The first run builds the sample (network): downloads the TREC 2021 topics + qrels into
data/trec/, draws 15 topics x 20 judged trials, fetches each trial from ClinicalTrials.gov and
saves data/fixtures/trec/sample.json. Every later run reads that file and never touches the
network.
"""

import argparse
import asyncio
from pathlib import Path

import httpx

from app.db import init_db
from app.eval.runs import BM25, current_git_sha, record_eval_run, score_bm25
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


def main(rebuild: bool) -> None:
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
    metrics = score_bm25(sample)
    row = record_eval_run(BM25, metrics, sample=sample, git_sha=git_sha)
    scores = "  ".join(f"{name} {value:.4f}" for name, value in metrics.items())
    print(
        f"bm25: {scores}  (eval_runs {row.id[:8]}, git {row.git_sha}, prompts {row.prompt_version})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rebuild", action="store_true", help="redraw and refetch the sample")
    main(parser.parse_args().rebuild)
