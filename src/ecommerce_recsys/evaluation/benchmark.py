from __future__ import annotations

import time
from collections.abc import Callable

import pandas as pd

from ecommerce_recsys.evaluation.metrics import (
    catalog_coverage,
    evaluate_predictions,
)
from ecommerce_recsys.recommendation.category_popularity import (
    CategoryPopularityRecommender,
)
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.recommendation.random_recommender import (
    RandomRecommender,
)
from ecommerce_recsys.recommendation.recent_popularity import (
    RecentPopularityRecommender,
)

Recommender = (
    PopularityRecommender
    | RecentPopularityRecommender
    | RandomRecommender
    | CategoryPopularityRecommender
    | ItemKNNRecommender
    | MatrixFactorizationRecommender
)

RecommendFunction = Callable[[str, list[str], int], list[str]]


def _recommend_for_user(
    recommender: Recommender,
    user_id: str,
    user_history: list[str],
    k: int,
) -> list[str]:
    """Adapt different recommender interfaces to one benchmark interface."""

    if isinstance(recommender, PopularityRecommender):
        return recommender.recommend(k)

    if isinstance(recommender, RecentPopularityRecommender):
        return recommender.recommend(k)

    if isinstance(recommender, RandomRecommender):
        return recommender.recommend(
            user_id=user_id,
            user_history=user_history,
            k=k,
        )

    if isinstance(recommender, CategoryPopularityRecommender):
        return recommender.recommend(user_history, k)

    if isinstance(recommender, ItemKNNRecommender):
        return recommender.recommend(user_history, k)

    if isinstance(recommender, MatrixFactorizationRecommender):
        return recommender.recommend(user_id, k)

    raise TypeError(f"Unsupported recommender type: {type(recommender).__name__}")


def _build_ground_truth(
    test: pd.DataFrame,
) -> dict[str, str]:
    """Build one held-out target item per evaluation user."""

    required_columns = {"user_id", "item_id"}
    missing = required_columns - set(test.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if test.empty:
        return {}

    return {str(row.user_id): str(row.item_id) for row in test.itertuples(index=False)}


def _build_user_histories(
    train: pd.DataFrame,
) -> dict[str, list[str]]:
    """Build training interaction history for each user."""

    required_columns = {"user_id", "item_id"}
    missing = required_columns - set(train.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    histories: dict[str, list[str]] = {}

    for user_id, group in train.groupby("user_id", sort=True):
        histories[str(user_id)] = group["item_id"].astype(str).tolist()

    return histories


def _calculate_latency_metrics(
    latencies_seconds: list[float],
) -> dict[str, float]:
    """Calculate recommendation latency statistics."""

    if not latencies_seconds:
        return {
            "latency_avg_ms": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
            "latency_p99_ms": 0.0,
        }

    latencies_ms = sorted(latency * 1000.0 for latency in latencies_seconds)

    def percentile(
        values: list[float],
        percentile_value: float,
    ) -> float:
        index = (len(values) - 1) * percentile_value

        lower = int(index)
        upper = min(
            lower + 1,
            len(values) - 1,
        )

        if lower == upper:
            return values[lower]

        weight = index - lower

        return values[lower] * (1.0 - weight) + values[upper] * weight

    return {
        "latency_avg_ms": round(
            sum(latencies_ms) / len(latencies_ms),
            6,
        ),
        "latency_p50_ms": round(
            percentile(latencies_ms, 0.50),
            6,
        ),
        "latency_p95_ms": round(
            percentile(latencies_ms, 0.95),
            6,
        ),
        "latency_p99_ms": round(
            percentile(latencies_ms, 0.99),
            6,
        ),
    }


def evaluate_recommender(
    recommender: Recommender,
    train: pd.DataFrame,
    test: pd.DataFrame,
    items: pd.DataFrame | None = None,
    k_values: tuple[int, ...] = (5, 10, 20),
    total_catalog_items: int | None = None,
) -> dict[str, float]:
    """Fit one recommender and evaluate it under a shared protocol."""

    if train.empty:
        raise ValueError("Train interactions must not be empty.")

    if not k_values:
        raise ValueError("k_values must not be empty.")

    if any(k <= 0 for k in k_values):
        raise ValueError("All k_values must be positive.")

    ground_truth = _build_ground_truth(test)

    if not ground_truth:
        return {}

    user_histories = _build_user_histories(train)

    if isinstance(
        recommender,
        (
            CategoryPopularityRecommender,
            RandomRecommender,
        ),
    ):
        if items is None:
            raise ValueError(
                "items must be provided for CategoryPopularityRecommender or RandomRecommender."
            )

        recommender.fit(
            interactions=train,
            items=items,
        )

    else:
        recommender.fit(train)

    predictions: dict[str, list[str]] = {}
    latencies_seconds: list[float] = []

    max_k = max(k_values)

    for user_id in ground_truth:
        history = user_histories.get(user_id, [])

        start = time.perf_counter()

        recommendations = _recommend_for_user(
            recommender=recommender,
            user_id=user_id,
            user_history=history,
            k=max_k,
        )

        elapsed = time.perf_counter() - start

        predictions[user_id] = recommendations
        latencies_seconds.append(elapsed)

    metrics = evaluate_predictions(
        predictions=predictions,
        ground_truth=ground_truth,
        k_values=k_values,
    )

    if total_catalog_items is not None:
        metrics["coverage"] = catalog_coverage(
            predictions.values(),
            total_catalog_items=total_catalog_items,
        )

    metrics.update(_calculate_latency_metrics(latencies_seconds))

    return metrics


def run_baseline_benchmark(
    train: pd.DataFrame,
    test: pd.DataFrame,
    recommenders: dict[str, Recommender],
    items: pd.DataFrame | None = None,
    k_values: tuple[int, ...] = (5, 10, 20),
    total_catalog_items: int | None = None,
) -> dict[str, dict[str, float]]:
    """Run multiple recommenders under the same evaluation protocol."""

    if not recommenders:
        raise ValueError("At least one recommender is required.")

    results: dict[str, dict[str, float]] = {}

    for name, recommender in recommenders.items():
        print(f"\nEvaluating: {name}")

        results[name] = evaluate_recommender(
            recommender=recommender,
            train=train,
            test=test,
            items=items,
            k_values=k_values,
            total_catalog_items=total_catalog_items,
        )

    return results
