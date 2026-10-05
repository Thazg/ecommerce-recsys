from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.benchmark import (
    evaluate_recommender,
)
from ecommerce_recsys.recommendation.item_knn import (
    ItemKNNRecommender,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TRAIN_PATH = PROJECT_ROOT / "data" / "processed" / "train.parquet"

TEST_PATH = PROJECT_ROOT / "data" / "processed" / "test.parquet"

SAMPLE_SIZE = 20_000
RANDOM_STATE = 42

SHRINKAGE_LAMBDAS = [
    0.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    200.0,
    500.0,
]


def main() -> None:
    print("Loading data...")

    train = pd.read_parquet(TRAIN_PATH)

    test = pd.read_parquet(TEST_PATH)

    test_users = (
        test["user_id"]
        .drop_duplicates()
        .sample(
            n=SAMPLE_SIZE,
            random_state=RANDOM_STATE,
        )
    )

    test_subset = test[test["user_id"].isin(test_users)].copy()

    print(f"Train users: {train['user_id'].nunique():,}")

    print(f"Full test users: {test['user_id'].nunique():,}")

    print(f"Subset test users: {test_subset['user_id'].nunique():,}")

    print(f"Subset test rows: {len(test_subset):,}")

    print("\nFitting ItemKNN once...")

    recommender = ItemKNNRecommender(
        n_neighbors=20,
        min_item_interactions=5,
        shrinkage_lambda=0.0,
    )

    recommender.fit(train)

    print("Fit complete.")

    results: list[dict[str, float]] = []

    for shrinkage_lambda in SHRINKAGE_LAMBDAS:
        print("\n" + "=" * 60)

        print(f"Evaluating shrinkage_lambda={shrinkage_lambda}")

        recommender.set_shrinkage_lambda(shrinkage_lambda)

        metrics = evaluate_recommender(
            recommender=recommender,
            train=train,
            test=test_subset,
            k_values=(5, 10, 20),
            total_catalog_items=None,
            fit=False,
            split_protocol="legacy_leave_last_out",
        )

        row = {
            "lambda": shrinkage_lambda,
            "HR@5": metrics["HR@5"],
            "MRR@5": metrics["MRR@5"],
            "NDCG@5": metrics["NDCG@5"],
            "HR@10": metrics["HR@10"],
            "MRR@10": metrics["MRR@10"],
            "NDCG@10": metrics["NDCG@10"],
            "HR@20": metrics["HR@20"],
            "MRR@20": metrics["MRR@20"],
            "NDCG@20": metrics["NDCG@20"],
            "latency_avg_ms": metrics["latency_avg_ms"],
            "latency_p50_ms": metrics["latency_p50_ms"],
            "latency_p95_ms": metrics["latency_p95_ms"],
            "latency_p99_ms": metrics["latency_p99_ms"],
        }

        results.append(row)

        print(f"HR@10:   {metrics['HR@10']:.6f}")

        print(f"MRR@10:  {metrics['MRR@10']:.6f}")

        print(f"NDCG@10: {metrics['NDCG@10']:.6f}")

        print(f"Latency: {metrics['latency_avg_ms']:.6f} ms")

    results_df = pd.DataFrame(results)

    print("\n" + "=" * 80)

    print("SHRINKAGE SENSITIVITY RESULTS")

    print(results_df.to_string(index=False))

    output_path = PROJECT_ROOT / "benchmarks" / "item_knn_shrinkage_sweep.csv"

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    results_df.to_csv(
        output_path,
        index=False,
    )

    print(f"\nSaved results to: {output_path}")


if __name__ == "__main__":
    main()
