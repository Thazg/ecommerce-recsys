from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from implicit.als import AlternatingLeastSquares


class MatrixFactorizationRecommender:
    def __init__(
        self,
        factors: int = 64,
        iterations: int = 20,
        regularization: float = 0.01,
    ) -> None:
        self.factors = factors
        self.iterations = iterations
        self.regularization = regularization

        self._model = None
        self._user_item_matrix: csr_matrix | None = None

        self._user_to_index: dict[str, int] = {}
        self._item_to_index: dict[str, int] = {}
        self._index_to_user: list[str] = []
        self._index_to_item: list[str] = []

    def _build_mappings(self, interactions: pd.DataFrame) -> None:
        users = sorted(interactions["user_id"].unique())
        items = sorted(interactions["item_id"].unique())

        self._user_to_index = {user_id: index for index, user_id in enumerate(users)}

        self._item_to_index = {item_id: index for index, item_id in enumerate(items)}

        self._index_to_user = users
        self._index_to_item = items

    def fit(self, interactions: pd.DataFrame) -> None:
        required_columns = {"user_id", "item_id"}
        missing = required_columns - set(interactions.columns)

        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        if interactions.empty:
            raise ValueError("Interactions must not be empty.")

        self._build_mappings(interactions)

        user_indices = interactions["user_id"].map(self._user_to_index)
        item_indices = interactions["item_id"].map(self._item_to_index)

        self._user_item_matrix = csr_matrix(
            (
                np.ones(
                    len(interactions),
                    dtype=np.float32,
                ),
                (user_indices, item_indices),
            ),
            shape=(
                len(self._user_to_index),
                len(self._item_to_index),
            ),
        )

        self._model = AlternatingLeastSquares(
            factors=self.factors,
            iterations=self.iterations,
            regularization=self.regularization,
            random_state=42,
        )

        self._model.fit(self._user_item_matrix)

    def recommend(self, user_id: str, k: int = 10) -> list[str]:
        if self._model is None:
            raise RuntimeError(
                "Model has not been fitted. Call fit() first."
            )

        if self._user_item_matrix is None:
            raise RuntimeError(
                "User-item matrix has not been built. Call fit() first."
            )

        if k <= 0:
            return []

        if user_id not in self._user_to_index:
            return []

        user_index = self._user_to_index[user_id]

        k = min(k, len(self._index_to_item))

        item_indices, _ = self._model.recommend(
            user_index,
            self._user_item_matrix[user_index],
            N=k,
            filter_already_liked_items=True,
        )

        return [
            self._index_to_item[item_index]
            for item_index in item_indices
        ]
