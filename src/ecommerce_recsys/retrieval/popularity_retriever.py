"""Global and cutoff-relative recent popularity candidate sources."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from ecommerce_recsys.recommendation.recent_popularity import recent_interactions
from ecommerce_recsys.retrieval.base import Candidate, CandidateGenerator, RetrievalContext


def interaction_counts(interactions: pd.DataFrame) -> pd.DataFrame:
    if "item_id" not in interactions:
        raise ValueError("Interactions require item_id.")
    if interactions["item_id"].isna().any():
        raise ValueError("Interaction item IDs must not be null.")
    return (
        interactions["item_id"]
        .astype(str)
        .value_counts()
        .rename_axis("item_id")
        .reset_index(name="count")
        .sort_values(["count", "item_id"], ascending=[False, True])
    )


class PopularityRetriever(CandidateGenerator):
    def __init__(
        self,
        interactions: pd.DataFrame,
        catalog: Iterable[str],
        *,
        window_days: int | None = None,
        cutoff: int | None = None,
    ) -> None:
        super().__init__(catalog)
        self.name = "global_popularity" if window_days is None else "recent_popularity"
        if window_days is not None:
            if window_days <= 0 or cutoff is None or "timestamp" not in interactions:
                raise ValueError(
                    "Recent retrieval requires positive window_days, cutoff, timestamps."
                )
            interactions = recent_interactions(interactions, window_days, cutoff=cutoff)
        counts = interaction_counts(interactions)
        self.ranking = tuple(
            (row.item_id, float(row.count))
            for row in counts.itertuples(index=False)
            if row.item_id in self.catalog
        )

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        return self._candidates(self.ranking, context, limit)
