"""Ranking metrics over TREC qrels labels (SPEC.md "7. Eval harness").

    ndcg_at_k([2, 0, 1, 2, ...])      # labels of the judged trials, in ranked order

    eligibility_accuracy([(2, True), (1, False), ...])   # (label, called eligible) pairs

Labels are 0 = not relevant, 1 = excluded, 2 = eligible. Only 2 counts as relevant, so both
ranking metrics use binary gain: an excluded trial ranked high is as wrong as an irrelevant one.
Accuracy asks the other question: on the trials the patient was judged against (labels 1 and
2), did the system call eligible vs excluded right?
"""

import math
from collections.abc import Iterable, Sequence

RELEVANT = 2
EXCLUDED = 1


def _gains(labels: Sequence[int]) -> list[int]:
    return [1 if label == RELEVANT else 0 for label in labels]


def precision_at_k(ranked_labels: Sequence[int], k: int = 10) -> float:
    """Eligible trials in the top `k`, over `k` (a short list still divides by `k`)."""
    return sum(_gains(ranked_labels[:k])) / k


def _dcg(gains: list[int]) -> float:
    return sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, start=1))


def ndcg_at_k(ranked_labels: Sequence[int], k: int = 10) -> float:
    """DCG of the top `k` over the DCG of the ideal top `k`; 0.0 when nothing is relevant."""
    gains = _gains(ranked_labels)
    ideal = _dcg(sorted(gains, reverse=True)[:k])
    return _dcg(gains[:k]) / ideal if ideal else 0.0


def eligibility_accuracy(calls: Iterable[tuple[int, bool]]) -> float | None:
    """Share of (label, called eligible) pairs called right, over labels 1 and 2 only (label 0
    trials are about some other condition, so eligible vs excluded doesn't apply). None when no
    pair has label 1 or 2."""
    scored = [
        called == (label == RELEVANT) for label, called in calls if label in (EXCLUDED, RELEVANT)
    ]
    return sum(scored) / len(scored) if scored else None
