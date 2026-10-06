from __future__ import annotations

import pandas as pd

SECONDS_PER_DAY = 24 * 60 * 60
MS_PER_DAY = SECONDS_PER_DAY * 1000


def recent_interactions(
    interactions: pd.DataFrame, window_days: int, *, cutoff: int | None = None
) -> pd.DataFrame:
    """Select a closed recency window ending at the declared snapshot cutoff."""
    missing = {"item_id", "timestamp"} - set(interactions.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if cutoff is None:
        cutoff = interactions["timestamp"].max()
    if (interactions["timestamp"] > cutoff).any():
        raise ValueError("Interactions follow the supplied cutoff.")
    return interactions.loc[interactions["timestamp"] >= cutoff - window_days * MS_PER_DAY]


class RecentPopularityRecommender:
    """Recommend items popular within a recent time window.

    Scores items by interaction count within the last `window_days` days
    ending at an explicit snapshot cutoff. Historical callers may omit the
    cutoff to use the latest training timestamp.

    Tie-breaking: count DESC, item_id ASC → deterministic ranking.
    """

    def __init__(self, window_days: int = 30) -> None:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        self._window_days = window_days
        self._ranking: list[str] = []
        self._fitted = False

    def fit(self, interactions: pd.DataFrame, *, cutoff: int | None = None) -> None:
        """Fit recent popularity ranking from interaction rows."""
        recent = recent_interactions(interactions, self._window_days, cutoff=cutoff)
        recent = recent.assign(item_id=recent["item_id"].astype(str))

        # 4. Count + sort (tie-break: item_id ASC)
        counts = (
            recent.groupby("item_id")
            .size()
            .reset_index(name="count")
            .sort_values(["count", "item_id"], ascending=[False, True])
        )

        self._ranking = counts["item_id"].astype(str).tolist()
        self._fitted = True

    def recommend(self, k: int) -> list[str]:
        """Return the top-k recently popular items."""
        if not self._fitted:
            raise RuntimeError("Model has not been fitted. Call fit() first.")

        if k <= 0:
            raise ValueError("k must be positive")
        return self._ranking[:k]
