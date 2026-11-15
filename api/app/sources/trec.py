"""TREC 2021 Clinical Trials topics + qrels, and the fixed eval sample (SPEC.md "7. Eval harness").

    topics = parse_topics(xml)                     # 75 patient descriptions
    qrels = parse_qrels(text)                      # 0 = not relevant, 1 = excluded, 2 = eligible
    picked = draw_sample(qrels, n_topics=15, per_topic=20, seed=SAMPLE_SEED)
    sample = await build_sample(topics, qrels, client=client)   # fetches each trial by NCT
    save_sample(sample)                            # data/fixtures/trec/sample.json (committed)

The sample is built once (`make eval` builds it when the file is missing) and every eval reads
the saved file, trial text included, so scores never move because a record changed upstream.
"""

import asyncio
import random
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.config import REPO_DIR
from app.sources import ctgov

TOPICS_URL = "https://www.trec-cds.org/topics2021.xml"
QRELS_URL = "https://trec.nist.gov/data/trials/qrels2021.txt"
RAW_DIR = REPO_DIR / "data" / "trec"  # downloaded topics + qrels (gitignored)
SAMPLE_PATH = REPO_DIR / "data" / "fixtures" / "trec" / "sample.json"

N_TOPICS = 15
PER_TOPIC = 20
SAMPLE_SEED = 2021
# One request at a time, paced under the API's rate limit (~50/min); bursts of ~300 lookups
# get 429s that outlast ctgov._get's retries.
FETCH_INTERVAL_S = 1.3
# What BM25 (and later the matcher) reads: titles, conditions, brief summary and criteria.
# No sites, so the saved sample stays small.
EVAL_FIELDS = (
    "IdentificationModule,StatusModule,ConditionsModule,EligibilityModule,BriefSummary,Phase"
)

Label = Literal[0, 1, 2]
# Strata, in the order that takes the remainder when `per_topic` doesn't split evenly.
LABELS: tuple[Label, ...] = (2, 1, 0)


class Topic(BaseModel, frozen=True):
    id: int
    text: str


class Judgment(BaseModel, frozen=True):
    topic_id: int
    nct_id: str
    label: Label


def parse_topics(xml: str) -> list[Topic]:
    root = ET.fromstring(xml)
    return [
        Topic(id=int(el.attrib["number"]), text=" ".join((el.text or "").split()))
        for el in root.iter("topic")
    ]


def parse_qrels(text: str) -> list[Judgment]:
    """`<topic> 0 <NCT ID> <label>` per line (the second column is unused)."""
    judgments = []
    for line in text.splitlines():
        if line.strip():
            topic, _, nct, label = line.split()
            judgments.append(
                Judgment.model_validate({"topic_id": topic, "nct_id": nct, "label": int(label)})
            )
    return judgments


def _quotas(per_topic: int) -> dict[Label, int]:
    base, extra = divmod(per_topic, len(LABELS))
    return {label: base + (i < extra) for i, label in enumerate(LABELS)}


def draw_sample(
    qrels: list[Judgment], *, n_topics: int, per_topic: int, seed: int
) -> list[Judgment]:
    """`n_topics` random topics × `per_topic` judged trials each, split evenly across the
    three labels. Topics with too few judgments in any label to fill its quota are skipped, so
    every topic has eligible trials to rank. Deterministic for a seed, whatever the input order.
    """
    rng = random.Random(seed)
    quotas = _quotas(per_topic)
    by_stratum: dict[tuple[int, Label], list[Judgment]] = defaultdict(list)
    for j in sorted(set(qrels), key=lambda j: (j.topic_id, j.nct_id)):
        by_stratum[(j.topic_id, j.label)].append(j)
    eligible = [
        t
        for t in sorted({j.topic_id for j in qrels})
        if all(len(by_stratum[(t, label)]) >= quotas[label] for label in LABELS)
    ]
    if len(eligible) < n_topics:
        raise ValueError(f"only {len(eligible)} topics can fill {quotas}; asked for {n_topics}")
    sample: list[Judgment] = []
    for topic in sorted(rng.sample(eligible, n_topics)):
        for label in LABELS:
            sample.extend(rng.sample(by_stratum[(topic, label)], quotas[label]))
    return sample


# --------------------------------------------------------------------------------------------
# The persisted sample
# --------------------------------------------------------------------------------------------


class TrecSample(BaseModel):
    """The fixed eval sample: sampled topics, the judgments whose trials survived the fetch,
    and each surviving trial's study JSON as fetched (so re-runs never depend on the API)."""

    seed: int
    n_topics: int
    per_topic: int
    topics: list[Topic]
    judgments: list[Judgment]
    trials: dict[str, dict[str, Any]]  # NCT ID -> v2 study JSON (EVAL_FIELDS only)
    dropped: dict[str, str]  # NCT ID -> why it left the sample

    @property
    def sample_size(self) -> int:
        """Judged (topic, trial) pairs that made it into the sample."""
        return len(self.judgments)


def eligibility_text(study: dict[str, Any]) -> str:
    module = study["protocolSection"].get("eligibilityModule", {})
    return str(module.get("eligibilityCriteria") or "").strip()


async def _fetch(nct: str, client: httpx.AsyncClient) -> dict[str, Any] | str:
    """The study, or why it can't be in the sample."""
    try:
        study = await ctgov.fetch_study(nct, client=client, fields=EVAL_FIELDS)
    except ctgov.StudyMovedError as e:
        # The judged record is now an alias; its replacement was never judged.
        return f"merged into {e.moved_to}"
    if study is None:
        return "not found"
    return study if eligibility_text(study) else "no eligibility text"


async def _fetch_all(
    ncts: list[str], client: httpx.AsyncClient, interval_s: float
) -> dict[str, dict[str, Any] | str]:
    fetched: dict[str, dict[str, Any] | str] = {}
    for i, nct in enumerate(ncts):
        if i and interval_s:
            await asyncio.sleep(interval_s)
        fetched[nct] = await _fetch(nct, client)
    return fetched


async def build_sample(
    topics: list[Topic],
    qrels: list[Judgment],
    *,
    client: httpx.AsyncClient,
    n_topics: int = N_TOPICS,
    per_topic: int = PER_TOPIC,
    seed: int = SAMPLE_SEED,
    interval_s: float = FETCH_INTERVAL_S,
) -> TrecSample:
    """Draw the sample and fetch each trial once by NCT ID. Trials ClinicalTrials.gov no
    longer has (gone, or merged into another record), or whose eligibility text is gone
    (records changed since 2021), are dropped along with their judgments."""
    picked = draw_sample(qrels, n_topics=n_topics, per_topic=per_topic, seed=seed)
    fetched = await _fetch_all(sorted({j.nct_id for j in picked}), client, interval_s)
    trials = {nct: s for nct, s in fetched.items() if not isinstance(s, str)}
    dropped = {nct: s for nct, s in fetched.items() if isinstance(s, str)}
    topic_ids = {j.topic_id for j in picked}
    return TrecSample(
        seed=seed,
        n_topics=n_topics,
        per_topic=per_topic,
        topics=[t for t in topics if t.id in topic_ids],
        judgments=[j for j in picked if j.nct_id in trials],
        trials=trials,
        dropped=dropped,
    )


def save_sample(sample: TrecSample, path: Path = SAMPLE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sample.model_dump_json(indent=1) + "\n")


def load_sample(path: Path = SAMPLE_PATH) -> TrecSample:
    return TrecSample.model_validate_json(path.read_text())
