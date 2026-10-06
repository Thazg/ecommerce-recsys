"""Popular candidates pooled across the categories present in request history."""

from __future__ import annotations

from heapq import merge

import pandas as pd

from ecommerce_recsys.retrieval.base import Candidate, CandidateGenerator, RetrievalContext
from ecommerce_recsys.retrieval.popularity_retriever import interaction_counts


class CategoryRetriever(CandidateGenerator):
    name = "category_popularity"

    def __init__(self, interactions: pd.DataFrame, items: pd.DataFrame) -> None:
        if not {"item_id", "category_id"}.issubset(items.columns):
            raise ValueError("Catalog requires item_id and category_id.")
        if items["item_id"].isna().any():
            raise ValueError("Catalog item IDs must not be null.")
        if items["item_id"].astype(str).duplicated().any():
            raise ValueError("Catalog item IDs must be unique.")
        super().__init__(items["item_id"])
        metadata = items.dropna(subset=["category_id"])
        self.categories = {
            str(row.item_id): str(row.category_id) for row in metadata.itertuples(index=False)
        }
        self.rankings: dict[str, list[tuple[str, float]]] = {}
        for row in interaction_counts(interactions).itertuples(index=False):
            category = self.categories.get(row.item_id)
            if category is not None:
                self.rankings.setdefault(category, []).append((row.item_id, float(row.count)))

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        categories = sorted(
            {self.categories[item] for item in context.history if item in self.categories}
        )
        ranked = merge(
            *(self.rankings.get(category, []) for category in categories),
            key=lambda entry: (-entry[1], entry[0]),
        )
        return self._candidates(ranked, context, limit)
