"""Offline evaluation metrics for Top-K ranking recommendations.

Milestone 3 — Temporal Split and Offline Evaluation Harness.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def hit_rate_at_k(
    recommended: Sequence[str | int],
    target: str | int,
    k: int,
) -> float:
    """Calculate Hit Rate at K (HR@K). Returns 1.0 if target is in Top-K else 0.0."""
    if k <= 0:
        raise ValueError("k must be a positive integer.")
    top_k = recommended[:k]
    return 1.0 if target in top_k else 0.0


def mrr_at_k(
    recommended: Sequence[str | int],
    target: str | int,
    k: int,
) -> float:
    """Calculate Mean Reciprocal Rank at K (MRR@K).

    Returns 1 / (rank + 1) where rank is 0-indexed position within Top-K, else 0.0.
    """
    if k <= 0:
        raise ValueError("k must be a positive integer.")
    top_k = recommended[:k]
    try:
        idx = top_k.index(target)
        return 1.0 / (idx + 1)
    except ValueError:
        return 0.0


def ndcg_at_k(
    recommended: Sequence[str | int],
    target: str | int,
    k: int,
) -> float:
    """Calculate Normalized Discounted Cumulative Gain at K (NDCG@K).

    For single-target leave-last-out evaluation:
    DCG@K = 1 / log2(rank + 2) where rank is 0-indexed position.
    IDCG@K = 1 / log2(1 + 1) = 1.0.
    """
    if k <= 0:
        raise ValueError("k must be a positive integer.")
    top_k = recommended[:k]
    try:
        idx = top_k.index(target)
        rank_1based = idx + 1
        return 1.0 / math.log2(rank_1based + 1)
    except ValueError:
        return 0.0


def catalog_coverage(
    all_recommendations: Iterable[Sequence[str | int]],
    total_catalog_items: int,
) -> float:
    """Calculate proportion of catalog items recommended across all users."""
    if total_catalog_items <= 0:
        raise ValueError("total_catalog_items must be positive.")
    recommended_set: set[str | int] = set()
    for rec_list in all_recommendations:
        recommended_set.update(rec_list)
    return round(len(recommended_set) / total_catalog_items, 6)


def evaluate_predictions(
    predictions: dict[str, Sequence[str | int]],
    ground_truth: dict[str, str | int],
    k_values: Sequence[int] = (5, 10, 20),
) -> dict[str, float]:
    """Evaluate Top-K recommendation rankings across all users."""
    if not ground_truth:
        return {}

    metrics: dict[str, float] = {}
    n_users = len(ground_truth)

    for k in k_values:
        total_hr = 0.0
        total_mrr = 0.0
        total_ndcg = 0.0

        for user_id, target in ground_truth.items():
            recs = predictions.get(user_id, [])
            total_hr += hit_rate_at_k(recs, target, k)
            total_mrr += mrr_at_k(recs, target, k)
            total_ndcg += ndcg_at_k(recs, target, k)

        metrics[f"HR@{k}"] = round(total_hr / n_users, 6)
        metrics[f"MRR@{k}"] = round(total_mrr / n_users, 6)
        metrics[f"NDCG@{k}"] = round(total_ndcg / n_users, 6)

    return metrics
