from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.benchmark import run_baseline_benchmark
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

DATA_DIR = Path("data/processed")
BENCHMARK_DIR = Path("benchmarks/baseline")
OUTPUT_PATH = BENCHMARK_DIR / "baseline_v2.json"

K_VALUES = (5, 10, 20)
RANDOM_SEED = 42
RECENT_WINDOW_DAYS = 30


def main() -> None:
    train_path = DATA_DIR / "train.parquet"
    test_path = DATA_DIR / "test.parquet"
    items_path = DATA_DIR / "items.parquet"

    print("Loading evaluation data...")

    train = pd.read_parquet(train_path)
    test = pd.read_parquet(test_path)
    items = pd.read_parquet(items_path)

    catalog_size = items["item_id"].nunique()

    print(f"Train: {train.shape}")
    print(f"Test: {test.shape}")
    print(f"Catalog: {catalog_size}")

    recommenders = {
        "random": RandomRecommender(
            seed=RANDOM_SEED,
        ),
        "popularity": PopularityRecommender(),
        "recent_popularity": RecentPopularityRecommender(
            window_days=RECENT_WINDOW_DAYS,
        ),
        "category_popularity": CategoryPopularityRecommender(),
        "item_knn_v1": ItemKNNRecommender(
            n_neighbors=20,
            min_item_interactions=5,
            shrinkage_lambda=0.0,
        ),
        "item_knn_v2": ItemKNNRecommender(
            n_neighbors=20,
            min_item_interactions=5,
            shrinkage_lambda=100.0,
        ),
        "als": MatrixFactorizationRecommender(
            factors=64,
            iterations=20,
            regularization=0.01,
            random_state=RANDOM_SEED,
        ),
    }

    print("\nRecommenders:")

    for name in recommenders:
        print(f"- {name}")

    print("\nEvaluation protocol:")
    print("- Training split: train.parquet")
    print("- Evaluation split: test.parquet")
    print(f"- K values: {K_VALUES}")
    print(f"- Random seed: {RANDOM_SEED}")
    print(f"- Recent popularity window: {RECENT_WINDOW_DAYS} days")
    print("- Coverage denominator: full catalog")
    print("- Latency: recommendation/inference only")
    print("- Fit/training time excluded from latency")

    print("\nEvaluating recommenders...")

    results = run_baseline_benchmark(
        train=train,
        test=test,
        recommenders=recommenders,
        items=items,
        k_values=K_VALUES,
        total_catalog_items=catalog_size,
    )

    artifact = {
        "benchmark_version": "v2",
        "evaluation_protocol": {
            "training_split": "train.parquet",
            "evaluation_split": "test.parquet",
            "k_values": list(K_VALUES),
            "catalog_size": catalog_size,
            "training_interactions": len(train),
            "evaluation_users": len(test),
            "random_seed": RANDOM_SEED,
            "recent_popularity_window_days": RECENT_WINDOW_DAYS,
            "latency_measurement": ("per-user recommendation latency; fit/training time excluded"),
        },
        "models": {
            "random": {
                "model_version": "v1",
                "seed": RANDOM_SEED,
                "metrics": results["random"],
            },
            "popularity": {
                "model_version": "v1",
                "metrics": results["popularity"],
            },
            "recent_popularity": {
                "model_version": "v1",
                "window_days": RECENT_WINDOW_DAYS,
                "metrics": results["recent_popularity"],
            },
            "category_popularity": {
                "model_version": "v1",
                "metrics": results["category_popularity"],
            },
            "item_knn_v1": {
                "model_version": "v1",
                "n_neighbors": 20,
                "min_item_interactions": 5,
                "shrinkage_lambda": 0.0,
                "metrics": results["item_knn_v1"],
            },
            "item_knn_v2": {
                "model_version": "v2",
                "n_neighbors": 20,
                "min_item_interactions": 5,
                "shrinkage_lambda": 100.0,
                "metrics": results["item_knn_v2"],
            },
            "als": {
                "model_version": "v1",
                "factors": 64,
                "iterations": 20,
                "regularization": 0.01,
                "metrics": results["als"],
            },
        },
    }

    BENCHMARK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            artifact,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nResults:")

    for name, metrics in results.items():
        print(f"\n{name}")

        for metric, value in metrics.items():
            print(f"  {metric}: {value}")

    print(f"\nBenchmark artifact written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
