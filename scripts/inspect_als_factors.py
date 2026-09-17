from pathlib import Path

import numpy as np
import pandas as pd

from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)

TRAIN_PATH = Path("data/processed/train.parquet")


def main() -> None:
    interactions = pd.read_parquet(TRAIN_PATH)

    model = MatrixFactorizationRecommender(
        factors=64,
        iterations=20,
        regularization=0.01,
        random_state=42,
    )

    model.fit(interactions)

    user_factors = model._model.user_factors
    item_factors = model._model.item_factors

    print("=== ALS Latent Factors ===")
    print(f"users: {len(model._user_to_index):,}")
    print(f"items: {len(model._item_to_index):,}")
    print(f"user_factors.shape: {user_factors.shape}")
    print(f"item_factors.shape: {item_factors.shape}")

    print("\n=== Factor Statistics ===")
    print(f"user factor mean: {user_factors.mean():.6f}")
    print(f"user factor std:  {user_factors.std():.6f}")
    print(f"item factor mean: {item_factors.mean():.6f}")
    print(f"item factor std:  {item_factors.std():.6f}")

    user_norms = np.linalg.norm(user_factors, axis=1)
    item_norms = np.linalg.norm(item_factors, axis=1)

    print("\n=== Embedding Norms ===")
    print(f"user norm mean: {user_norms.mean():.6f}")
    print(f"user norm p95:  {np.percentile(user_norms, 95):.6f}")
    print(f"item norm mean: {item_norms.mean():.6f}")
    print(f"item norm p95:  {np.percentile(item_norms, 95):.6f}")

    user_id = model._index_to_user[0]
    user_index = model._user_to_index[user_id]

    print("\n=== Example User ===")
    print(f"user_id: {user_id}")
    print(f"user_index: {user_index}")
    print(f"user_vector[:10]: {user_factors[user_index][:10]}")


if __name__ == "__main__":
    main()
