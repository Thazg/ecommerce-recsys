"""Exact latent-factor retrieval from a fitted implicit ALS model."""

from collections.abc import Iterable

from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.retrieval.base import (
    Candidate,
    CandidateGenerator,
    RetrievalContext,
    validate_limit,
)


class MFRetriever(CandidateGenerator):
    name = "als"

    def __init__(self, model: MatrixFactorizationRecommender, catalog: Iterable[str]) -> None:
        super().__init__(catalog)
        self.model = model
        if not set(model.item_ids).issubset(self.catalog):
            raise ValueError("ALS model items must belong to the training-time catalog.")

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        validate_limit(limit)
        ranked = self.model.score_candidates(context.user_id, limit, context.history)
        return self._candidates(ranked, context, limit)
