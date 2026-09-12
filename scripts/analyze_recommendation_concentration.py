from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender

DATA_DIR = Path("data/processed")


def main() -> None:
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    test = pd.read_parquet(DATA_DIR / "test.parquet")

    recommender = ItemKNNRecommender(
        n_neighbors=20,
        min_item_interactions=5,
    )
    recommender.fit(train)

    user_histories = (
        train.groupby("user_id")["item_id"].apply(lambda x: x.astype(str).tolist()).to_dict()
    )

    recommendation_counts: Counter[str] = Counter()

    for user_id in test["user_id"].astype(str):
        history = user_histories.get(user_id, [])

        recommendations = recommender.recommend(
            user_history=history,
            k=20,
        )

        recommendation_counts.update(recommendations)

    total_recommendations = sum(recommendation_counts.values())
    unique_items = len(recommendation_counts)

    print(f"Total recommendation slots: {total_recommendations:,}")
    print(f"Unique recommended items: {unique_items:,}")

    print("\nRecommendation concentration:")

    for top_n in (10, 100, 1000):
        top_count = sum(count for _, count in recommendation_counts.most_common(top_n))

        percentage = top_count / total_recommendations * 100

        print(f"Top {top_n:,} items: {top_count:,} recommendations ({percentage:.2f}%)")

    print("\nTop 20 items:")

    for rank, (item_id, count) in enumerate(
        recommendation_counts.most_common(20),
        start=1,
    ):
        percentage = count / total_recommendations * 100

        print(f"{rank:2d}. {item_id}: {count:,} ({percentage:.2f}%)")


if __name__ == "__main__":
    main()
