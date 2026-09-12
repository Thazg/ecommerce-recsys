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
    users_with_recommendations = 0

    for user_id in test["user_id"].astype(str):
        history = user_histories.get(user_id, [])

        recommendations = recommender.recommend(
            user_history=history,
            k=20,
        )

        if recommendations:
            users_with_recommendations += 1

        recommendation_counts.update(recommendations)

    print(f"Test users: {len(test):,}")
    print(f"Users with recommendations: {users_with_recommendations:,}")
    print(f"Unique recommended items: {len(recommendation_counts):,}")

    print("\nTop 20 recommended items:")
    for item_id, count in recommendation_counts.most_common(20):
        print(f"{item_id}: {count:,}")


if __name__ == "__main__":
    main()
