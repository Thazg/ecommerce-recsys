from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.metrics import evaluate_predictions
from ecommerce_recsys.recommendation.recent_popularity import RecentPopularityRecommender

DATA_DIR = Path("data/processed")


def build_ground_truth(df: pd.DataFrame) -> dict[str, str]:
    """Build user -> target item mapping from a leave-last-out split."""
    return dict(zip(df["user_id"], df["item_id"], strict=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Recent Popularity on a temporal split.")
    parser.add_argument(
        "--split",
        choices=("val", "test"),
        default="val",
        help="Evaluation split to use.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=30,
        help="Time window in days for recent popularity (default: 30).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write evaluation results as JSON.",
    )
    args = parser.parse_args()

    train = pd.read_parquet(DATA_DIR / "train.parquet")

    recommender = RecentPopularityRecommender(window_days=args.window_days)
    recommender.fit(train)

    evaluation_split = pd.read_parquet(DATA_DIR / f"{args.split}.parquet")
    ground_truth = build_ground_truth(evaluation_split)

    ranking = recommender.recommend(20)
    predictions = {user_id: ranking for user_id in ground_truth}

    metrics = evaluate_predictions(
        predictions=predictions,
        ground_truth=ground_truth,
        k_values=(5, 10, 20),
    )

    print(f"Recent Popularity (window={args.window_days}d) — {args.split.capitalize()}")
    print("=" * 55)
    print(f"Users evaluated        : {len(ground_truth):,}")
    print(f"Training interactions  : {len(train):,}")
    print(f"Recent catalog size    : {len(recommender._ranking):,}")
    print()

    for metric_name, value in metrics.items():
        print(f"{metric_name:8s}: {value:.6f}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "benchmark_version": "v1",
            "model": "recent_popularity",
            "model_version": "v1",
            "evaluation_split": args.split,
            "training_split": "train.parquet",
            "window_days": args.window_days,
            "k_values": [5, 10, 20],
            "training_interactions": len(train),
            "evaluation_users": len(ground_truth),
            "recent_catalog_size": len(recommender._ranking),
            "metrics": metrics,
        }

        args.output.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

        print()
        print(f"Benchmark written to: {args.output}")


if __name__ == "__main__":
    main()
