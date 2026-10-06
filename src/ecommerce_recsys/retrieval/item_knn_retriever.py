"""Retrieve collaborative item neighbors without hidden popularity fallback."""

from collections.abc import Iterable

from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.retrieval.base import Candidate, CandidateGenerator, RetrievalContext


class ItemKNNRetriever(CandidateGenerator):
    name = "item_knn"

    def __init__(self, model: ItemKNNRecommender, catalog: Iterable[str]) -> None:
        super().__init__(catalog)
        self.model = model

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        return self._candidates(self.model.score_candidates(list(context.history)), context, limit)
