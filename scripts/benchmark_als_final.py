from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.benchmark import evaluate_recommender
from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)

DATA_DIR = Path("data/processed")
BENCHMARK_DIR = Path("benchmarks/mf")
OUTPUT_PATH = BENCHMARK_DIR / "als_final_v1.json"

K_VALUES = (5, 10, 20)

FINAL_FACTORS = 128
FINAL_ITERATIONS = 20
FINAL_REGULARIZATION = 0.01
RANDOM_SEED = 42


def main() -> None:
    print("Loading final evaluation data...")

    train = pd.read_parquet(DATA_DIR / "train.parquet")
    test = pd.read_parquet(DATA_DIR / "test.parquet")
    items = pd.read_parquet(DATA_DIR / "items.parquet")

    catalog_size = items["item_id"].nunique()

    print(f"Train: {train.shape}")
    print(f"Test: {test.shape}")
    print(f"Catalog: {catalog_size}")

    recommender = MatrixFactorizationRecommender(
        factors=FINAL_FACTORS,
        iterations=FINAL_ITERATIONS,
        regularization=FINAL_REGULARIZATION,
        random_state=RANDOM_SEED,
    )

    print("\nFitting final ALS configuration on train split...")

    recommender.fit(train)

    print("Evaluating on test split...")

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=test,
        k_values=K_VALUES,
        total_catalog_items=catalog_size,
        fit=False,
    )

    artifact = {
        "experiment_version": "v1",
        "model": "implicit_als",
        "selection_protocol": {
            "selection_split": "val.parquet",
            "selected_config": {
                "factors": FINAL_FACTORS,
                "iterations": FINAL_ITERATIONS,
                "regularization": FINAL_REGULARIZATION,
            },
        },
        "evaluation_protocol": {
            "training_split": "train.parquet",
            "evaluation_split": "test.parquet",
            "k_values": list(K_VALUES),
            "catalog_size": catalog_size,
            "training_interactions": len(train),
            "evaluation_users": len(test),
            "random_seed": RANDOM_SEED,
            "latency_measurement": (
                "per-user recommendation latency; "
                "fit/training time excluded"
            ),
        },
        "config": {
            "factors": FINAL_FACTORS,
            "iterations": FINAL_ITERATIONS,
            "regularization": FINAL_REGULARIZATION,
        },
        "metrics": metrics,
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

    print(f"\nFinal ALS artifact written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()