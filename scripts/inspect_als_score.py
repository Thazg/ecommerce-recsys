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

    # Pick the first known user.
    user_id = model._index_to_user[0]
    user_index = model._user_to_index[user_id]

    # Pick the first item.
    item_id = model._index_to_item[0]
    item_index = model._item_to_index[item_id]

    user_vector = model._model.user_factors[user_index]
    item_vector = model._model.item_factors[item_index]

    manual_score = float(np.dot(user_vector, item_vector))

    # Ask implicit for the score of this user against this item.
    scores = model._model.user_factors[user_index] @ model._model.item_factors.T
    implicit_score = float(scores[item_index])

    print("=== ALS Score Inspection ===")
    print(f"user_id: {user_id}")
    print(f"user_index: {user_index}")
    print(f"item_id: {item_id}")
    print(f"item_index: {item_index}")

    print("\n=== Vector Shapes ===")
    print(f"user_vector.shape: {user_vector.shape}")
    print(f"item_vector.shape: {item_vector.shape}")

    print("\n=== Score ===")
    print(f"manual dot product: {manual_score:.12f}")
    print(f"matrix multiplication: {implicit_score:.12f}")
    print(f"absolute difference: {abs(manual_score - implicit_score):.12e}")


if __name__ == "__main__":
    main()
