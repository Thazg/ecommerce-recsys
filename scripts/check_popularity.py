from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecommerce_recsys.recommendation.popularity import PopularityRecommender

DATA_DIR = Path("data/processed")


def main() -> None:
    train = pd.read_parquet(DATA_DIR / "train.parquet")
    val = pd.read_parquet(DATA_DIR / "val.parquet")

    recommender = PopularityRecommender()
    recommender.fit(train)

    top_5 = recommender.recommend(5)
    top_10 = recommender.recommend(10)
    top_20 = recommender.recommend(20)

    print("Global Popularity — Sanity Checks")
    print("=" * 45)

    print(f"Training interactions : {len(train):,}")
    print(f"Validation users      : {val['user_id'].nunique():,}")
    print()

    print("Top-K sizes")
    print(f"Top-5  : {len(top_5)}")
    print(f"Top-10 : {len(top_10)}")
    print(f"Top-20 : {len(top_20)}")
    print()

    print("Top-20 items")
    print(top_20)
    print()

    top_20_set = set(top_20)

    target_hits = val["item_id"].isin(top_20_set)

    print("Validation target check")
    print(f"Targets in Top-20 : {target_hits.sum():,}")
    print(f"Target hit rate   : {target_hits.mean():.6f}")
    print()

    user_histories = train.groupby("user_id")["item_id"].agg(set)

    overlap_counts = []

    for user_id in val["user_id"]:
        history = user_histories.get(user_id, set())
        overlap_counts.append(len(history.intersection(top_20_set)))

    overlap = pd.Series(overlap_counts)

    print("User-history overlap with Global Top-20")
    print(f"Users with overlap > 0 : {(overlap > 0).sum():,}")
    print(f"Mean overlap           : {overlap.mean():.4f}")
    print(f"Max overlap            : {overlap.max()}")


if __name__ == "__main__":
    main()
