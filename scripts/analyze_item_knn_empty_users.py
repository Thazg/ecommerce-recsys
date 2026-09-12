from __future__ import annotations

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

    total_users = 0
    no_indexed_history = 0
    has_indexed_history = 0
    no_candidates = 0
    no_positive_neighbor = 0

    for user_id in test["user_id"].astype(str):
        history = user_histories.get(user_id, [])

        indexed_history = [item for item in history if item in recommender._item_neighbors]

        has_positive_neighbor = False

        for item in indexed_history:
            for neighbor_id, similarity, support in recommender._item_neighbors[item]:
                if similarity > 0.0:
                    has_positive_neighbor = True
                    break

            if has_positive_neighbor:
                break

        candidates = set()

        for item in indexed_history:
            for neighbor_id, similarity, support in recommender._item_neighbors[item]:
                if neighbor_id not in history:
                    candidates.add(neighbor_id)

        if not candidates:
            no_candidates += 1

        if indexed_history and not has_positive_neighbor:
            no_positive_neighbor += 1

        total_users += 1

        if not indexed_history:
            no_indexed_history += 1
        else:
            has_indexed_history += 1

    print(f"Total test users: {total_users:,}")
    print(f"No indexed history: {no_indexed_history:,}")
    print(f"Has indexed history: {has_indexed_history:,}")
    print(f"No candidates: {no_candidates:,}")
    print(f"No positive-similarity neighbor: {no_positive_neighbor:,}")


if __name__ == "__main__":
    main()
