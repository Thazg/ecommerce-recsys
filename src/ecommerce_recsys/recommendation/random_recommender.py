from __future__ import annotations

import hashlib
import random

import pandas as pd


class RandomRecommender:
    """Recommend random unseen catalog items with deterministic sampling."""

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._catalog: list[str] = []

    def fit(
        self,
        interactions: pd.DataFrame,
        items: pd.DataFrame,
    ) -> None:
        """Fit the recommender using the full catalog."""

        required_interaction_columns = {"item_id"}
        missing_interaction_columns = required_interaction_columns - set(interactions.columns)

        if missing_interaction_columns:
            raise ValueError(
                f"Missing required interaction columns: {sorted(missing_interaction_columns)}"
            )

        required_item_columns = {"item_id"}
        missing_item_columns = required_item_columns - set(items.columns)

        if missing_item_columns:
            raise ValueError(f"Missing required item columns: {sorted(missing_item_columns)}")

        self._catalog = (
            items["item_id"].dropna().astype(str).drop_duplicates().sort_values().tolist()
        )

        if not self._catalog:
            raise ValueError("Catalog must contain at least one item.")

    def recommend(
        self,
        user_id: str,
        user_history: list[str],
        k: int,
    ) -> list[str]:
        """Return deterministic random unseen catalog items."""

        if not self._catalog:
            raise RuntimeError("Model has not been fitted. Call fit() first.")

        if k <= 0:
            raise ValueError("k must be positive.")

        seen = {str(item_id) for item_id in user_history}

        if len(seen) >= len(self._catalog):
            return []

        user_seed = self._build_user_seed(user_id)
        rng = random.Random(user_seed)

        recommendations: list[str] = []
        recommended = set()

        available = len(self._catalog) - len(seen)
        k = min(k, available)
        if k == 0:
            return []

        while len(recommendations) < k:
            item_id = rng.choice(self._catalog)

            if item_id in seen or item_id in recommended:
                continue

            recommendations.append(item_id)
            recommended.add(item_id)

        return recommendations

    def _build_user_seed(self, user_id: str) -> int:
        """Build a stable per-user seed from the global seed and user ID."""

        payload = f"{self._seed}:{user_id}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()

        return int.from_bytes(digest[:8], byteorder="big")
