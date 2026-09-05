"""Unit tests for offline evaluation ranking metrics.

Milestone 3 — Temporal Split and Offline Evaluation Harness.
"""

import math

import pytest

from ecommerce_recsys.evaluation.metrics import (
    catalog_coverage,
    evaluate_predictions,
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
)


def test_hit_rate_at_k():
    recs = ["item_a", "item_b", "item_c", "item_d", "item_e"]

    # Target in Top-3
    assert hit_rate_at_k(recs, "item_b", k=3) == 1.0

    # Target at position 5 (outside Top-3)
    assert hit_rate_at_k(recs, "item_e", k=3) == 0.0

    # Target not in recommendations
    assert hit_rate_at_k(recs, "item_z", k=5) == 0.0


def test_mrr_at_k():
    recs = ["item_a", "item_b", "item_c", "item_d"]

    # Rank 1 -> 1 / 1 = 1.0
    assert mrr_at_k(recs, "item_a", k=4) == 1.0

    # Rank 2 -> 1 / 2 = 0.5
    assert mrr_at_k(recs, "item_b", k=4) == 0.5

    # Rank 3 -> 1 / 3
    assert pytest.approx(mrr_at_k(recs, "item_c", k=4), 0.0001) == 1.0 / 3.0

    # Outside cutoff
    assert mrr_at_k(recs, "item_d", k=3) == 0.0


def test_ndcg_at_k():
    recs = ["item_a", "item_b", "item_c", "item_d"]

    # Rank 1 -> 1 / log2(2) = 1.0
    assert ndcg_at_k(recs, "item_a", k=4) == 1.0

    # Rank 2 -> 1 / log2(3) ≈ 0.63093
    expected_rank2 = 1.0 / math.log2(3)
    assert pytest.approx(ndcg_at_k(recs, "item_b", k=4), 0.0001) == expected_rank2

    # Rank 3 -> 1 / log2(4) = 0.5
    assert ndcg_at_k(recs, "item_c", k=4) == 0.5

    # Outside cutoff
    assert ndcg_at_k(recs, "item_d", k=2) == 0.0


def test_catalog_coverage():
    all_recs = [
        ["item_1", "item_2"],
        ["item_2", "item_3"],
        ["item_1", "item_4"],
    ]
    # 4 unique items out of 10 in catalog -> 4/10 = 0.4
    assert catalog_coverage(all_recs, total_catalog_items=10) == 0.4


def test_evaluate_predictions_batch():
    predictions = {
        "user_1": ["item_a", "item_b", "item_c"],  # target 'item_a' at rank 1
        "user_2": ["item_x", "item_b", "item_y"],  # target 'item_b' at rank 2
        "user_3": ["item_m", "item_n", "item_p"],  # target 'item_z' not found
    }
    ground_truth = {
        "user_1": "item_a",
        "user_2": "item_b",
        "user_3": "item_z",
    }

    results = evaluate_predictions(predictions, ground_truth, k_values=[2, 3])

    # HR@2: user_1 hit (1.0), user_2 hit (1.0), user_3 miss (0.0) -> mean = 2/3 ≈ 0.666667
    assert results["HR@2"] == round(2.0 / 3.0, 6)

    # MRR@2: user_1 (1.0), user_2 (0.5), user_3 (0.0) -> mean = 1.5 / 3 = 0.5
    assert results["MRR@2"] == 0.5


def test_invalid_k_raises_error():
    with pytest.raises(ValueError):
        hit_rate_at_k(["a", "b"], "a", k=0)
