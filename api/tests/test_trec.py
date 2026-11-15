"""TREC 2021 Clinical Trials topics + qrels, and the fixed stratified sample."""

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.sources.trec import (
    EVAL_FIELDS,
    Judgment,
    Topic,
    TrecSample,
    build_sample,
    draw_sample,
    first_topics,
    load_sample,
    parse_qrels,
    parse_topics,
    save_sample,
)
from tests.ctgov_fake import FakeCtgov

TOPICS_XML = """<topics task="2021 TREC Clinical Trials">
<topic number="1">
Patient is a 45-year-old man with a history of anaplastic astrocytoma.
</topic>
<topic number="2">A 32-year-old woman with type 2 diabetes &amp; CKD.</topic>
</topics>
"""

QRELS = """1 0 NCT00002569 1
1 0 NCT00002806 0
2 0 NCT00002814 2
"""


def test_parse_topics_reads_number_and_stripped_text() -> None:
    topics = parse_topics(TOPICS_XML)

    assert [t.id for t in topics] == [1, 2]
    assert (
        topics[0].text == "Patient is a 45-year-old man with a history of anaplastic astrocytoma."
    )
    assert topics[1].text == "A 32-year-old woman with type 2 diabetes & CKD."


def test_parse_qrels_reads_topic_nct_and_label() -> None:
    assert parse_qrels(QRELS) == [
        Judgment(topic_id=1, nct_id="NCT00002569", label=1),
        Judgment(topic_id=1, nct_id="NCT00002806", label=0),
        Judgment(topic_id=2, nct_id="NCT00002814", label=2),
    ]


def _qrels(topics: range, per_label: int) -> list[Judgment]:
    return [
        Judgment(topic_id=t, nct_id=f"NCT{t:03d}{label}{i:04d}", label=label)
        for t in topics
        for label in (0, 1, 2)
        for i in range(per_label)
    ]


def test_sample_draws_n_topics_with_per_topic_trials_split_across_labels() -> None:
    qrels = _qrels(range(1, 31), per_label=10)

    sample = draw_sample(qrels, n_topics=15, per_topic=20, seed=7)

    per_topic = Counter(j.topic_id for j in sample)
    assert len(per_topic) == 15
    assert set(per_topic.values()) == {20}
    for topic in per_topic:
        labels = Counter(j.label for j in sample if j.topic_id == topic)
        assert labels == {2: 7, 1: 7, 0: 6}  # the remainder goes to eligible first
    assert set(sample) <= set(qrels)


def test_sample_skips_topics_too_thin_in_any_label() -> None:
    thin = [j for j in _qrels(range(90, 100), per_label=10) if j.label != 1 or j.nct_id[-1] < "6"]
    qrels = _qrels(range(1, 16), per_label=10) + thin  # topics 90-99 have only 6 excluded

    sample = draw_sample(qrels, n_topics=15, per_topic=20, seed=7)

    assert {j.topic_id for j in sample} == set(range(1, 16))


def test_sample_says_so_when_too_few_topics_qualify() -> None:
    with pytest.raises(ValueError, match="only 3 topics"):
        draw_sample(_qrels(range(1, 4), per_label=10), n_topics=15, per_topic=20, seed=7)


def test_sample_is_deterministic_per_seed() -> None:
    qrels = _qrels(range(1, 31), per_label=10)

    first = draw_sample(qrels, n_topics=15, per_topic=20, seed=7)

    assert draw_sample(list(reversed(qrels)), n_topics=15, per_topic=20, seed=7) == first
    assert draw_sample(qrels, n_topics=15, per_topic=20, seed=8) != first


def _study(nct: str, eligibility: str | None) -> dict[str, Any]:
    proto: dict[str, Any] = {
        "identificationModule": {"nctId": nct, "briefTitle": f"Trial {nct}"},
        "statusModule": {"lastUpdatePostDateStruct": {"date": "2025-01-01"}},
    }
    if eligibility is not None:
        proto["eligibilityModule"] = {"eligibilityCriteria": eligibility}
    return {"protocolSection": proto}


async def test_build_sample_fetches_each_trial_once_and_drops_ones_without_criteria(
    tmp_path: Path,
) -> None:
    topics = [Topic(id=1, text="t one"), Topic(id=2, text="t two"), Topic(id=3, text="t three")]
    qrels = [
        Judgment(topic_id=1, nct_id="NCT00000001", label=2),
        Judgment(topic_id=1, nct_id="NCT00000002", label=1),
        Judgment(topic_id=1, nct_id="NCT00000003", label=0),
        Judgment(topic_id=2, nct_id="NCT00000001", label=0),  # shared with topic 1
        Judgment(topic_id=2, nct_id="NCT00000004", label=1),
        Judgment(topic_id=2, nct_id="NCT00000005", label=2),
    ]
    fake = FakeCtgov(
        {
            "NCT00000001": _study("NCT00000001", "Inclusion: adults"),
            "NCT00000002": _study("NCT00000002", "  \n "),  # blanked upstream
            "NCT00000004": _study("NCT00000004", None),  # module gone
            "NCT00000005": _study("NCT00000005", "Inclusion: T2D"),
        }
    )  # NCT00000003 is unknown: 404
    async with fake.client() as client:
        sample = await build_sample(
            topics, qrels, client=client, n_topics=2, per_topic=3, seed=1, interval_s=0
        )

    assert [t.id for t in sample.topics] == [1, 2]
    assert sorted(sample.trials) == ["NCT00000001", "NCT00000005"]
    assert sample.dropped == {
        "NCT00000002": "no eligibility text",
        "NCT00000003": "not found",
        "NCT00000004": "no eligibility text",
    }
    assert {(j.topic_id, j.nct_id) for j in sample.judgments} == {
        (1, "NCT00000001"),
        (2, "NCT00000001"),
        (2, "NCT00000005"),
    }
    assert sample.sample_size == 3
    paths = [r.url.path.rsplit("/", 1)[1] for r in fake.requests]
    assert sorted(paths) == [f"NCT0000000{i}" for i in range(1, 6)]
    assert {r.url.params["fields"] for r in fake.requests} == {EVAL_FIELDS}

    path = tmp_path / "trec" / "sample.json"
    save_sample(sample, path)
    assert load_sample(path) == sample


async def test_build_sample_drops_trials_merged_into_another_record() -> None:
    qrels = [
        Judgment(topic_id=1, nct_id="NCT00000001", label=2),
        Judgment(topic_id=1, nct_id="NCT00000002", label=1),
        Judgment(topic_id=1, nct_id="NCT00000003", label=0),
    ]
    fake = FakeCtgov(
        {nct: _study(nct, "Inclusion: adults") for nct in ("NCT00000001", "NCT00000002")},
        moved={"NCT00000003": "NCT09999999"},  # the judged record is now an alias
    )
    async with fake.client() as client:
        sample = await build_sample(
            [Topic(id=1, text="t")],
            qrels,
            client=client,
            n_topics=1,
            per_topic=3,
            seed=1,
            interval_s=0,
        )

    assert sample.dropped == {"NCT00000003": "merged into NCT09999999"}
    assert sorted(sample.trials) == ["NCT00000001", "NCT00000002"]
    assert len(fake.requests) == 3  # the redirect is not followed


def _three_topic_sample() -> TrecSample:
    # Topics in sample order 3, 1, 2; NCT0B is judged under both topic 3 and topic 2.
    judged = {3: ["NCT0A", "NCT0B"], 1: ["NCT0C"], 2: ["NCT0B", "NCT0D"]}
    return TrecSample(
        seed=1,
        n_topics=3,
        per_topic=2,
        topics=[Topic(id=t, text=f"topic {t}") for t in judged],
        judgments=[
            Judgment(topic_id=t, nct_id=nct, label=2) for t, ncts in judged.items() for nct in ncts
        ],
        trials={
            nct: _study(nct, "Inclusion: adults") for nct in ("NCT0A", "NCT0B", "NCT0C", "NCT0D")
        },
        dropped={"NCT0E": "not found"},
    )


def test_first_topics_keeps_the_first_n_topics_their_judgments_and_trials() -> None:
    partial = first_topics(_three_topic_sample(), 2)

    assert [t.id for t in partial.topics] == [3, 1]
    assert [(j.topic_id, j.nct_id) for j in partial.judgments] == [
        (3, "NCT0A"),
        (3, "NCT0B"),
        (1, "NCT0C"),
    ]
    assert sorted(partial.trials) == ["NCT0A", "NCT0B", "NCT0C"]
    assert partial.partial
    assert not _three_topic_sample().partial
    assert not first_topics(_three_topic_sample(), 3).partial  # all of them is the full sample


@pytest.mark.parametrize("n", [0, -1, 4])
def test_first_topics_rejects_an_out_of_range_count(n: int) -> None:
    with pytest.raises(ValueError, match=r"must be between 1 and 3"):
        first_topics(_three_topic_sample(), n)
