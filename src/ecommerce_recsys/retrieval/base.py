"""Shared contracts for candidate generation independently of final ranking."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    user_id: str | None = None
    history: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.history is None or isinstance(self.history, (str, bytes)):
            raise ValueError("History must be a sequence of item IDs.")
        if self.user_id is not None:
            object.__setattr__(self, "user_id", str(self.user_id))
        if any(item is None for item in self.history):
            raise ValueError("History item IDs must not be null.")
        object.__setattr__(self, "history", tuple(dict.fromkeys(map(str, self.history))))


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """One-based rank in the source's eligible, seen-filtered candidate list."""

    source: str
    score: float
    rank: int

    def __post_init__(self) -> None:
        if (
            not self.source
            or not math.isfinite(self.score)
            or isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank <= 0
        ):
            raise ValueError("Source evidence requires a name, finite score and positive rank.")


@dataclass(frozen=True, slots=True)
class Candidate:
    item_id: str
    score: float
    evidence: tuple[SourceEvidence, ...]

    def __post_init__(self) -> None:
        if self.item_id is None:
            raise ValueError("Candidate item ID must not be null.")
        if not isinstance(self.item_id, str):
            object.__setattr__(self, "item_id", str(self.item_id))
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))
        if not self.item_id or not math.isfinite(self.score) or not self.evidence:
            raise ValueError("Candidates require an item ID, finite score and source evidence.")
        if len({entry.source for entry in self.evidence}) != len(self.evidence):
            raise ValueError("A candidate cannot contain duplicate source evidence.")


def validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("Candidate limit must be a positive integer.")


class CandidateGenerator(ABC):
    """Read-only retrieval from a previously fitted training-time snapshot."""

    name: str

    def __init__(self, catalog: Iterable[str]) -> None:
        values = tuple(catalog)
        if any(item is None for item in values):
            raise ValueError("Catalog item IDs must not be null.")
        self.catalog = frozenset(map(str, values))

    @abstractmethod
    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        """Return ordered, unique, eligible, unseen candidates up to limit."""

    def _candidates(
        self, ranked: Iterable[tuple[str, float]], context: RetrievalContext, limit: int
    ) -> list[Candidate]:
        validate_limit(limit)
        seen = set(context.history)
        output = []
        added: set[str] = set()
        for item, score in ranked:
            item = str(item)
            if item in seen or item in added or item not in self.catalog:
                continue
            evidence = SourceEvidence(self.name, float(score), len(output) + 1)
            output.append(Candidate(item, float(score), (evidence,)))
            added.add(item)
            if len(output) == limit:
                break
        return output
