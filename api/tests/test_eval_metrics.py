"""nDCG@10 and P@10 on hand-computed rankings (label 2 = relevant, 0 and 1 are not)."""

import pytest

from app.eval.metrics import ndcg_at_k, precision_at_k

LOG2_3 = 1.584962500721156  # log2(3); 1/LOG2_3 = 0.63093 is the discount at rank 2


def test_precision_counts_only_eligible_in_the_top_k() -> None:
    # 3 of the top 10 are label 2; the 1s (excluded) don't count, nor does the 2 at rank 11.
    ranked = [2, 1, 0, 2, 1, 0, 0, 2, 1, 0, 2]
    assert precision_at_k(ranked, k=10) == pytest.approx(0.3)


def test_precision_divides_by_k_even_when_fewer_are_ranked() -> None:
    assert precision_at_k([2, 2], k=10) == pytest.approx(0.2)


def test_ndcg_of_a_hand_computed_ranking() -> None:
    # DCG  = 1/log2(2) + 0 + 1/log2(4) = 1 + 0.5     = 1.5
    # IDCG = 1/log2(2) + 1/log2(3)     = 1 + 0.63093 = 1.63093
    assert ndcg_at_k([2, 0, 2], k=10) == pytest.approx(1.5 / (1 + 1 / LOG2_3))
    assert ndcg_at_k([2, 0, 2], k=10) == pytest.approx(0.91972, abs=1e-5)


def test_ndcg_cuts_at_k_but_ideal_counts_every_relevant_judgment() -> None:
    # k=2 sees [0, 2]: DCG = 1/log2(3) = 0.63093. The ideal top 2 is [2, 2]: 1 + 0.63093.
    assert ndcg_at_k([0, 2, 2], k=2) == pytest.approx(0.38685, abs=1e-5)


def test_ndcg_perfect_and_worst_orderings() -> None:
    assert ndcg_at_k([2, 2, 1, 0], k=10) == pytest.approx(1.0)
    assert ndcg_at_k([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2], k=10) == 0.0


def test_ndcg_is_zero_when_nothing_is_relevant() -> None:
    assert ndcg_at_k([0, 1, 0], k=10) == 0.0
