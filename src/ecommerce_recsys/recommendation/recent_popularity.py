from __future__ import annotations

import pandas as pd

SECONDS_PER_DAY = 24 * 60 * 60
MS_PER_DAY = SECONDS_PER_DAY * 1000


class RecentPopularityRecommender:
    """Recommend items popular within a recent time window.

    Scores items by interaction count within the last `window_days` days
    of the training data (relative to the latest timestamp in train).

    Tie-breaking: count DESC, item_id ASC → deterministic ranking.
    """

    def __init__(self, window_days: int = 30) -> None:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        self._window_days = window_days
        self._ranking: list[str] = []

    def fit(self, interactions: pd.DataFrame) -> None:
        """Fit recent popularity ranking from interaction rows."""
        required_columns = {"item_id", "timestamp"}
        missing = required_columns - set(interactions.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        # ① Tìm cutoff = thời điểm cuối cùng trong train
        cutoff = interactions["timestamp"].max()

        # ② Tính window theo milliseconds
        window_ms = self._window_days * MS_PER_DAY

        # ③ Filter chỉ giữ lại interactions trong window
        mask = interactions["timestamp"] >= cutoff - window_ms
        recent = interactions.loc[mask]

        # ④ Count + sort (tie-break: item_id ASC)
        counts = (
            recent.groupby("item_id")
            .size()
            .reset_index(name="count")
            .sort_values(["count", "item_id"], ascending=[False, True])
        )

        self._ranking = counts["item_id"].astype(str).tolist()

    def recommend(self, k: int) -> list[str]:
        """Return the top-k recently popular items."""
        if k <= 0:
            raise ValueError("k must be positive")
        return self._ranking[:k]
