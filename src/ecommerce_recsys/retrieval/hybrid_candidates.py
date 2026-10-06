"""Deterministic reciprocal-rank fusion with retained source evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from ecommerce_recsys.retrieval.base import (
    Candidate,
    CandidateGenerator,
    RetrievalContext,
    SourceEvidence,
    validate_limit,
)


class HybridCandidateGenerator(CandidateGenerator):
    def __init__(
        self,
        sources: Sequence[CandidateGenerator],
        *,
        name: str = "hybrid",
        pool_size: int = 1000,
        rank_constant: float = 60.0,
    ) -> None:
        validate_limit(pool_size)
        if not sources or len({source.name for source in sources}) != len(sources):
            raise ValueError("Hybrid requires sources with unique names.")
        if not math.isfinite(rank_constant) or rank_constant < 0:
            raise ValueError("Fusion rank constant must be finite and nonnegative.")
        if any(source.catalog != sources[0].catalog for source in sources):
            raise ValueError("Hybrid sources must share the same eligible catalog.")
        super().__init__(sources[0].catalog)
        self.sources = tuple(sources)
        self.name = name
        self.pool_size = pool_size
        self.rank_constant = rank_constant

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        self._validate_request(limit)
        pools = {source.name: source.generate(context, self.pool_size) for source in self.sources}
        return self.fuse(pools, context, limit)

    def _validate_request(self, limit: int) -> None:
        validate_limit(limit)
        if limit > self.pool_size:
            raise ValueError("Requested limit exceeds the configured hybrid pool size.")

    def fuse(
        self,
        pools: Mapping[str, list[Candidate]],
        context: RetrievalContext,
        limit: int,
    ) -> list[Candidate]:
        """Fuse already retrieved source pools; evaluation can reuse source calls."""
        self._validate_request(limit)
        expected = {source.name for source in self.sources}
        if set(pools) != expected:
            raise ValueError("Pools must match the configured hybrid sources.")
        seen = set(context.history)
        evidence: dict[str, list[SourceEvidence]] = {}
        for source in self.sources:
            added: set[str] = set()
            for candidate in pools[source.name][: self.pool_size]:
                item = candidate.item_id
                if item in seen or item not in self.catalog or item in added:
                    continue
                if len(candidate.evidence) != 1 or candidate.evidence[0].source != source.name:
                    raise ValueError(
                        "Hybrid inputs must be direct candidates from their named source."
                    )
                entry = candidate.evidence[0]
                if entry.score != candidate.score:
                    raise ValueError("Source evidence score must match its candidate score.")
                evidence.setdefault(item, []).append(entry)
                added.add(item)
        scored = [
            (sum(1 / (self.rank_constant + e.rank) for e in entries), item, entries)
            for item, entries in evidence.items()
        ]
        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        return [Candidate(item, score, tuple(entries)) for score, item, entries in scored[:limit]]
