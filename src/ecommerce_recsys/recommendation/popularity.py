from __future__ import annotations

import pandas as pd


class PopularityRecommender:
    """Recommend globally popular items based on training interactions."""

    def __init__(self) -> None:
        self._ranking: list[str] = []

    def fit(self, interactions: pd.DataFrame) -> None:
        """Fit popularity ranking from interaction rows."""
        required_columns = {"item_id"}

        missing_columns = required_columns - set(interactions.columns)
        if missing_columns:
            raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

        counts = interactions.groupby("item_id").size()

        self._ranking = (
            counts.sort_values(ascending=False, kind="stable").index.astype(str).tolist()
        )

    def recommend(self, k: int) -> list[str]:
        """Return the top-k globally popular items."""
        if k <= 0:
            raise ValueError("k must be positive")

        return self._ranking[:k]
