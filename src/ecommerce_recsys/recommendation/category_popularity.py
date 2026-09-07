from __future__ import annotations

import pandas as pd


class CategoryPopularityRecommender:
    """Recommend popular items within categories based on training interactions."""

    def __init__(self) -> None:
        self._item_categories: dict[str, str] = {}
        self._category_ranking: dict[str, list[str]] = {}
        self._global_ranking: list[str] = []

    def fit(
        self,
        interactions: pd.DataFrame,
        items: pd.DataFrame,
    ) -> None:
        """Fit category popularity rankings from training interactions."""

        required_interaction_columns = {"item_id"}
        missing_interaction_columns = required_interaction_columns - set(interactions.columns)

        if missing_interaction_columns:
            raise ValueError(
                f"Missing required interaction columns: {sorted(missing_interaction_columns)}"
            )

        required_item_columns = {"item_id", "category_id"}
        missing_item_columns = required_item_columns - set(items.columns)

        if missing_item_columns:
            raise ValueError(f"Missing required item columns: {sorted(missing_item_columns)}")

        item_metadata = items[["item_id", "category_id"]].copy()
        item_metadata["item_id"] = item_metadata["item_id"].astype(str)

        item_metadata = item_metadata.dropna(subset=["category_id"])
        item_metadata["category_id"] = item_metadata["category_id"].astype(str)

        self._item_categories = dict(
            zip(
                item_metadata["item_id"],
                item_metadata["category_id"],
                strict=True,
            )
        )

        item_counts = interactions.groupby("item_id").size().reset_index(name="count")

        item_counts["item_id"] = item_counts["item_id"].astype(str)

        item_counts = item_counts.sort_values(
            ["count", "item_id"],
            ascending=[False, True],
        )

        self._global_ranking = item_counts["item_id"].tolist()

        category_counts = item_counts.merge(
            item_metadata,
            on="item_id",
            how="inner",
        )

        category_counts = category_counts.sort_values(
            ["category_id", "count", "item_id"],
            ascending=[True, False, True],
        )

        self._category_ranking = {
            str(category_id): group["item_id"].tolist()
            for category_id, group in category_counts.groupby(
                "category_id",
                sort=True,
            )
        }

    def recommend(
        self,
        user_history: list[str],
        k: int,
    ) -> list[str]:
        """Return top-k popular items from the user's categories."""

        if not self._global_ranking:
            raise RuntimeError("Model has not been fitted. Call fit() first.")

        if k <= 0:
            raise ValueError("k must be positive")

        seen = {str(item_id) for item_id in user_history}

        categories = {
            self._item_categories[item_id] for item_id in seen if item_id in self._item_categories
        }

        recommendations: list[str] = []

        for category_id in sorted(categories):
            for item_id in self._category_ranking.get(category_id, []):
                if item_id in seen or item_id in recommendations:
                    continue

                recommendations.append(item_id)

                if len(recommendations) >= k:
                    return recommendations

        for item_id in self._global_ranking:
            if item_id in seen or item_id in recommendations:
                continue

            recommendations.append(item_id)

            if len(recommendations) >= k:
                break

        return recommendations
