from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.neighbors import NearestNeighbors


class ItemKNNRecommender:
    """Item-based collaborative filtering using cosine similarity.

    For each item, stores top-n_neighbors most similar items based on
    cosine similarity of their user interaction vectors.

    At inference time, scores candidate items by summing their similarity
    to all items in the user's history. Excludes already-seen items.

    Tie-breaking: score DESC, item_id ASC → deterministic ranking.
    """

    def __init__(
        self,
        n_neighbors: int = 20,
        min_item_interactions: int = 5,
    ) -> None:
        if n_neighbors <= 0:
            raise ValueError("n_neighbors must be positive")
        if min_item_interactions <= 0:
            raise ValueError("min_item_interactions must be positive")
        self._n_neighbors = n_neighbors
        self._min_item_interactions = min_item_interactions
        self._item_neighbors: dict[str, list[tuple[str, float]]] = {}

    def fit(self, interactions: pd.DataFrame) -> None:
        """Fit item-item similarity from interaction data.

        Steps:
          ① Filter to items with enough interactions.
          ② Build sparse binary user-item matrix.
          ③ Find top-n_neighbors per item via cosine similarity.
          ④ Store neighbors, excluding self.
        """
        required_columns = {"user_id", "item_id"}
        missing = required_columns - set(interactions.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        # ① Filter items with too few interactions (reduce computation)
        item_counts = interactions["item_id"].value_counts()
        eligible_items = item_counts[item_counts >= self._min_item_interactions].index
        df = interactions[interactions["item_id"].isin(eligible_items)].copy()

        if df.empty:
            self._item_neighbors = {}
            return

        # ② Build index mappings — sort items for determinism
        users = df["user_id"].unique()
        items = sorted(df["item_id"].astype(str).unique())
        user_to_idx = {u: i for i, u in enumerate(users)}
        item_to_idx = {it: i for i, it in enumerate(items)}

        # ③ Build sparse user-item binary matrix (1 if interacted, clip duplicates)
        rows = df["user_id"].map(user_to_idx).values
        cols = df["item_id"].astype(str).map(item_to_idx).values
        data = np.ones(len(df), dtype=np.float32)
        X = csr_matrix((data, (rows, cols)), shape=(len(users), len(items)))

        # ④ Find top-n_neighbors per item
        # item_matrix: (n_items, n_users) — each row is one item's user vector
        item_matrix = X.T.tocsr()
        n_neighbors = min(self._n_neighbors + 1, len(items))  # +1 because self is included
        nn = NearestNeighbors(n_neighbors=n_neighbors, metric="cosine", algorithm="brute")
        nn.fit(item_matrix)
        distances, indices = nn.kneighbors(item_matrix)
        similarities = 1.0 - distances  # cosine distance → similarity

        # ⑤ Store neighbors, skipping rank 0 (always self with sim=1.0)
        self._item_neighbors = {}
        for i, item_id in enumerate(items):
            neighbors = [
                (items[indices[i][rank]], float(similarities[i][rank]))
                for rank in range(1, len(indices[i]))
                if similarities[i][rank] > 0.0
            ]
            self._item_neighbors[item_id] = neighbors

    def recommend(self, user_history: list[str], k: int) -> list[str]:
        """Return top-k items based on similarity to user history.

        Args:
            user_history: Items the user has already interacted with.
            k: Number of recommendations to return.

        Returns:
            Top-k item IDs excluding seen items.
            Returns [] if user history has no items in the trained space.
        """
        if not self._item_neighbors:
            raise RuntimeError("Model has not been fitted. Call fit() first.")
        if k <= 0:
            raise ValueError("k must be positive")
        if not user_history:
            return []

        seen = {str(i) for i in user_history}
        scores: dict[str, float] = {}

        for history_item in user_history:
            for neighbor_id, sim in self._item_neighbors.get(str(history_item), []):
                if neighbor_id not in seen:
                    scores[neighbor_id] = scores.get(neighbor_id, 0.0) + sim

        # Tie-breaking: score DESC, item_id ASC
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return [item_id for item_id, _ in ranked[:k]]
