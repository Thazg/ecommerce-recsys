from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.metrics import evaluate_predictions
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender

DATA_DIR = Path("data/processed")


def build_ground_truth(df: pd.DataFrame) -> dict[str, str]:
    """Build user -> target item mapping from a leave-last-out split."""
    return dict(zip(df["user_id"], df["item_id"], strict=True))


def build_user_histories(train: pd.DataFrame) -> dict[str, list[str]]:
    """Build user -> list of interacted items from training data."""
    return train.groupby("user_id")["item_id"].apply(lambda x: x.astype(str).tolist()).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ItemKNN on a temporal split.")
    parser.add_argument(
        "--split",
        choices=("val", "test"),
        default="val",
        help="Evaluation split to use.",
    )
    parser.add_argument(
        "--n-neighbors",
        type=int,
        default=20,
        help="Number of item neighbors (default: 20).",
    )
    parser.add_argument(
        "--min-item-interactions",
        type=int,
        default=5,
        help="Minimum interactions for an item to be included (default: 5).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write evaluation results as JSON.",
    )
    args = parser.parse_args()

    # Load training data and fit model
    print("Loading training data...")
    train = pd.read_parquet(DATA_DIR / "train.parquet")

    print(
        f"Fitting ItemKNN (n_neighbors={args.n_neighbors}, min_item_interactions={args.min_item_interactions})..."
    )
    t0 = time.perf_counter()
    recommender = ItemKNNRecommender(
        n_neighbors=args.n_neighbors,
        min_item_interactions=args.min_item_interactions,
    )
    recommender.fit(train)
    fit_time = time.perf_counter() - t0
    print(f"Fit completed in {fit_time:.1f}s — {len(recommender._item_neighbors):,} items indexed")

    # Build user histories from train
    user_histories = build_user_histories(train)

    # Load evaluation split
    evaluation_split = pd.read_parquet(DATA_DIR / f"{args.split}.parquet")
    ground_truth = build_ground_truth(evaluation_split)

    # Generate personalized predictions
    print(f"Generating predictions for {len(ground_truth):,} users...")
    t1 = time.perf_counter()
    predictions: dict[str, list[str]] = {}
    cold_start_users = 0

    for user_id in ground_truth:
        history = user_histories.get(user_id, [])
        recs = recommender.recommend(user_history=history, k=20)
        predictions[user_id] = recs
        if not recs:
            cold_start_users += 1

    predict_time = time.perf_counter() - t1
    print(f"Predictions completed in {predict_time:.1f}s")

    # Compute metrics
    metrics = evaluate_predictions(
        predictions=predictions,
        ground_truth=ground_truth,
        k_values=(5, 10, 20),
    )

    # Print results
    print()
    print(
        f"ItemKNN (k={args.n_neighbors}, min_interactions={args.min_item_interactions}) — {args.split.capitalize()}"
    )
    print("=" * 60)
    print(f"Users evaluated        : {len(ground_truth):,}")
    print(
        f"Cold-start users (no recs): {cold_start_users:,} ({cold_start_users / len(ground_truth) * 100:.1f}%)"
    )
    print(f"Training interactions  : {len(train):,}")
    print(f"Items indexed          : {len(recommender._item_neighbors):,}")
    print(f"Fit time               : {fit_time:.1f}s")
    print(f"Predict time           : {predict_time:.1f}s")
    print()
    for metric_name, value in metrics.items():
        print(f"{metric_name:8s}: {value:.6f}")

    # Optionally save to JSON
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "benchmark_version": "v1",
            "model": "item_knn",
            "model_version": "v1",
            "evaluation_split": args.split,
            "training_split": "train.parquet",
            "n_neighbors": args.n_neighbors,
            "min_item_interactions": args.min_item_interactions,
            "k_values": [5, 10, 20],
            "training_interactions": len(train),
            "evaluation_users": len(ground_truth),
            "cold_start_users": cold_start_users,
            "items_indexed": len(recommender._item_neighbors),
            "fit_time_seconds": round(fit_time, 2),
            "predict_time_seconds": round(predict_time, 2),
            "metrics": metrics,
        }

        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print()
        print(f"Benchmark written to: {args.output}")


if __name__ == "__main__":
    main()
