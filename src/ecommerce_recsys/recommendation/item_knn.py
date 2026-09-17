from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.neighbors import NearestNeighbors

from ecommerce_recsys.recommendation.popularity import (
    PopularityRecommender,
)


class ItemKNNRecommender:
    """Item-based collaborative filtering with cosine similarity.

    Stores top-N neighbors per item from binary user-item vectors,
    scores candidates by summing shrinkage-adjusted similarities
    over the user's history.

    Empty history returns []. Unknown history falls back to popularity.
    Tie-breaking: score DESC, item_id ASC.
    """

    def __init__(
        self,
        n_neighbors: int = 20,
        min_item_interactions: int = 5,
        shrinkage_lambda: float = 10.0,
    ) -> None:
        if n_neighbors <= 0:
            raise ValueError("n_neighbors must be positive")

        if min_item_interactions <= 0:
            raise ValueError("min_item_interactions must be positive")

        if shrinkage_lambda < 0:
            raise ValueError("shrinkage_lambda must be non-negative")

        self._n_neighbors = n_neighbors
        self._min_item_interactions = min_item_interactions
        self._shrinkage_lambda = shrinkage_lambda

        self._item_neighbors: dict[
            str,
            list[tuple[str, float, int]],
        ] = {}

        self._fallback_recommender: PopularityRecommender | None = None

    def fit(
        self,
        interactions: pd.DataFrame,
    ) -> None:
        """Fit item-item similarity from interaction data."""
        required_columns = {
            "user_id",
            "item_id",
        }

        missing = required_columns - set(interactions.columns)

        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        if interactions.empty:
            raise ValueError("Interactions must not be empty.")

        self._fallback_recommender = PopularityRecommender()

        self._fallback_recommender.fit(interactions)

        item_counts = interactions["item_id"].value_counts()

        eligible_items = item_counts[item_counts >= self._min_item_interactions].index

        df = interactions[interactions["item_id"].isin(eligible_items)].copy()
        df = df.drop_duplicates(subset=["user_id", "item_id"]).copy()
        df["user_id"] = df["user_id"].astype(str)
        df["item_id"] = df["item_id"].astype(str)

        if df.empty:
            self._item_neighbors = {}
            return

        users = sorted(df["user_id"].astype(str).unique())

        items = sorted(df["item_id"].astype(str).unique())

        user_to_idx = {user_id: index for index, user_id in enumerate(users)}

        item_to_idx = {item_id: index for index, item_id in enumerate(items)}

        rows = df["user_id"].astype(str).map(user_to_idx).values

        cols = df["item_id"].astype(str).map(item_to_idx).values

        data = np.ones(
            len(df),
            dtype=np.float32,
        )

        X = csr_matrix(
            (
                data,
                (rows, cols),
            ),
            shape=(
                len(users),
                len(items),
            ),
        )

        item_matrix = X.T.tocsr()

        n_neighbors = min(
            self._n_neighbors + 1,
            len(items),
        )

        nn = NearestNeighbors(
            n_neighbors=n_neighbors,
            metric="cosine",
            algorithm="brute",
        )

        nn.fit(item_matrix)

        distances, indices = nn.kneighbors(item_matrix)

        similarities = 1.0 - distances

        self._item_neighbors = {}

        for i, item_id in enumerate(items):
            neighbors: list[tuple[str, float, int]] = []

            for rank in range(
                1,
                len(indices[i]),
            ):
                similarity = float(similarities[i][rank])

                if similarity <= 0.0:
                    continue

                neighbor_index = indices[i][rank]

                neighbor_id = items[neighbor_index]

                support = int(item_matrix[i].dot(item_matrix[neighbor_index].T)[0, 0])

                neighbors.append(
                    (
                        neighbor_id,
                        similarity,
                        support,
                    )
                )

            self._item_neighbors[item_id] = neighbors

    def set_shrinkage_lambda(
        self,
        shrinkage_lambda: float,
    ) -> None:
        """Update shrinkage strength without refitting the model."""
        if shrinkage_lambda < 0:
            raise ValueError("shrinkage_lambda must be non-negative")

        self._shrinkage_lambda = shrinkage_lambda

    def _adjust_similarity(
        self,
        similarity: float,
        support: int,
    ) -> float:
        """Apply support-aware similarity shrinkage."""
        if self._shrinkage_lambda == 0.0:
            return similarity

        return similarity * support / (support + self._shrinkage_lambda)

    def recommend(
        self,
        user_history: list[str],
        k: int,
    ) -> list[str]:
        """Return top-k items based on similarity to user history."""
        if self._fallback_recommender is None:
            raise RuntimeError("Model has not been fitted. Call fit() first.")

        if k <= 0:
            raise ValueError("k must be positive")

        if not user_history:
            return []

        seen = {str(item_id) for item_id in user_history}

        known_history = list(
            dict.fromkeys(str(i) for i in user_history if str(i) in self._item_neighbors)
        )

        if not known_history:
            fallback_recommendations = self._fallback_recommender.recommend(k + len(seen))

            return [item_id for item_id in fallback_recommendations if item_id not in seen][:k]

        scores: dict[
            str,
            float,
        ] = {}

        for history_item in known_history:
            for (
                neighbor_id,
                raw_similarity,
                support,
            ) in self._item_neighbors[history_item]:
                if neighbor_id in seen:
                    continue

                similarity = self._adjust_similarity(
                    similarity=raw_similarity,
                    support=support,
                )

                scores[neighbor_id] = (
                    scores.get(
                        neighbor_id,
                        0.0,
                    )
                    + similarity
                )

        ranked = sorted(
            scores.items(),
            key=lambda x: (
                -x[1],
                x[0],
            ),
        )

        return [item_id for item_id, _ in ranked[:k]]
