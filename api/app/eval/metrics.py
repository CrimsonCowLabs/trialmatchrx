"""Ranking metrics over TREC qrels labels (SPEC.md "7. Eval harness").

    ndcg_at_k([2, 0, 1, 2, ...])      # labels of the judged trials, in ranked order

Labels are 0 = not relevant, 1 = excluded, 2 = eligible. Only 2 counts as relevant, so both
metrics use binary gain: an excluded trial ranked high is as wrong as an irrelevant one.
"""

import math
from collections.abc import Sequence

RELEVANT = 2


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
