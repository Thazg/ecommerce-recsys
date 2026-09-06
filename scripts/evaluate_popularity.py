from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.metrics import evaluate_predictions
from ecommerce_recsys.recommendation.popularity import PopularityRecommender

DATA_DIR = Path("data/processed")


def build_ground_truth(df: pd.DataFrame) -> dict[str, str]:
    """Build user -> target item mapping from a leave-last-out split."""
    return dict(zip(df["user_id"], df["item_id"], strict=True))


def evaluate_split(
    recommender: PopularityRecommender,
    split: str,
) -> dict[str, float]:
    """Evaluate global popularity on a temporal evaluation split."""
    df = pd.read_parquet(DATA_DIR / f"{split}.parquet")
    ground_truth = build_ground_truth(df)

    ranking = recommender.recommend(20)

    predictions = {user_id: ranking for user_id in ground_truth}

    return evaluate_predictions(
        predictions=predictions,
        ground_truth=ground_truth,
        k_values=(5, 10, 20),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Global Popularity on a temporal split.")
    parser.add_argument(
        "--split",
        choices=("val", "test"),
        default="val",
        help="Evaluation split to use.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write evaluation results as JSON.",
    )
    args = parser.parse_args()

    train = pd.read_parquet(DATA_DIR / "train.parquet")

    recommender = PopularityRecommender()
    recommender.fit(train)

    evaluation_split = pd.read_parquet(DATA_DIR / f"{args.split}.parquet")
    ground_truth = build_ground_truth(evaluation_split)

    metrics = evaluate_split(
        recommender=recommender,
        split=args.split,
    )

    print(f"Global Popularity — {args.split.capitalize()}")
    print("=" * 45)
    print(f"Users evaluated       : {len(ground_truth):,}")
    print(f"Training interactions : {len(train):,}")
    print(f"Popularity catalog size: {len(recommender._ranking):,}")
    print()

    for metric_name, value in metrics.items():
        print(f"{metric_name:8s}: {value:.6f}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "benchmark_version": "v1",
            "model": "global_popularity",
            "model_version": "v1",
            "evaluation_split": args.split,
            "training_split": "train.parquet",
            "k_values": [5, 10, 20],
            "training_interactions": len(train),
            "evaluation_users": len(ground_truth),
            "catalog_size": len(recommender._ranking),
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
