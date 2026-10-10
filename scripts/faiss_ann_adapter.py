"""Experimental Faiss HNSW adapter for paired Two-Tower retrieval tests."""

from __future__ import annotations

from time import perf_counter

import numpy as np

from ecommerce_recsys.retrieval.base import (
    Candidate,
    CandidateGenerator,
    RetrievalContext,
    validate_limit,
)
from ecommerce_recsys.retrieval.two_tower import TwoTowerRetriever, encode_history


class FaissTwoTowerANN(CandidateGenerator):
    """Search fitted Two-Tower vectors without hidden exact or popularity fallback."""

    name = "two_tower_ann"

    def __init__(
        self,
        exact: TwoTowerRetriever,
        *,
        graph_degree: int,
        ef_construction: int,
        ef_search: int,
        max_budget: int = 1000,
    ) -> None:
        import faiss

        if exact.model is None or exact.item_vectors is None:
            raise ValueError("ANN requires a fitted Two-Tower retriever.")
        if min(graph_degree, ef_construction, ef_search, max_budget) <= 0:
            raise ValueError("ANN index settings and maximum budget must be positive.")
        super().__init__(exact.catalog)
        self.exact = exact
        self.model_snapshot = exact.model
        self.source_vectors = exact.item_vectors
        self.item_ids = exact.item_ids
        self.item_to_index = exact.item_to_index
        self.item_vectors = np.ascontiguousarray(exact.item_vectors, dtype=np.float32)
        if not np.isfinite(self.item_vectors).all():
            raise ValueError("ANN item vectors must be finite.")
        self.max_budget = max_budget
        self.ef_search = ef_search
        self.search_calls = 0
        self.max_effective_ef_search = 0
        faiss.omp_set_num_threads(1)
        started = perf_counter()
        self.index = faiss.IndexHNSWFlat(
            self.item_vectors.shape[1], graph_degree, faiss.METRIC_INNER_PRODUCT
        )
        self.index.hnsw.efConstruction = ef_construction
        self.index.hnsw.efSearch = ef_search
        self.index.add(self.item_vectors)
        self.build_seconds = perf_counter() - started
        if self.index.ntotal != len(self.item_ids):
            raise ValueError("ANN index does not contain the complete fold catalog.")
        self.serialized_index_bytes = int(faiss.serialize_index(self.index).nbytes)

    def _query_vector(self, context: RetrievalContext) -> np.ndarray | None:
        import torch

        history = encode_history(
            context.ordered_history, self.item_to_index, self.exact.max_history
        )
        if not history:
            return None
        with torch.no_grad():
            ids = torch.full((1, self.exact.max_history), -1, dtype=torch.long)
            ids[0, -len(history) :] = torch.tensor(history)
            vector = self.exact.model.encode_user(ids).cpu().numpy()[0]
        query = np.ascontiguousarray(vector, dtype=np.float32)
        if not np.isfinite(query).all():
            raise ValueError("Two-Tower query vector must be finite.")
        return query

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        validate_limit(limit)
        if (
            self.exact.model is not self.model_snapshot
            or self.exact.item_vectors is not self.source_vectors
        ):
            raise ValueError("ANN index is stale after Two-Tower refit.")
        if limit > self.max_budget:
            raise ValueError("ANN request exceeds the fixed maximum budget.")
        if not context.ordered_history:
            return []
        query = self._query_vector(context)
        if query is None:
            return []
        seen_indices = {
            self.item_to_index[item] for item in context.history if item in self.item_to_index
        }
        available = len(self.item_ids) - len(seen_indices)
        goal = min(self.max_budget, available)
        if not goal:
            return []
        search_k = min(
            len(self.item_ids), max(2 * self.max_budget, self.max_budget + len(seen_indices))
        )
        while True:
            effective_ef = max(self.ef_search, search_k)
            self.index.hnsw.efSearch = effective_ef
            self.max_effective_ef_search = max(self.max_effective_ef_search, effective_ef)
            _, found = self.index.search(query[None, :], search_k)
            self.search_calls += 1
            shortlist = [
                int(index) for index in found[0] if index >= 0 and int(index) not in seen_indices
            ]
            if len(shortlist) >= goal or search_k == len(self.item_ids):
                break
            search_k = min(len(self.item_ids), 2 * search_k)
        if not shortlist:
            return []
        shortlist = list(dict.fromkeys(shortlist))
        scores = self.item_vectors[shortlist] @ query
        if not np.isfinite(scores).all():
            raise ValueError("ANN shortlist produced nonfinite exact scores.")
        ranked_indices = sorted(
            range(len(shortlist)),
            key=lambda position: (-float(scores[position]), self.item_ids[shortlist[position]]),
        )[:goal]
        ranked = [
            (self.item_ids[shortlist[position]], float(scores[position]))
            for position in ranked_indices
        ]
        return self._candidates(ranked, context, limit)
