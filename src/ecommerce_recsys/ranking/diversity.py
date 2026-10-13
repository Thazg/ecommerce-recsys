"""Deterministic category-aware re-ranking of a fixed learned candidate order."""

from __future__ import annotations

import math
from collections.abc import Sequence
from numbers import Real

import numpy as np


def category_novelty_order(
    item_ids: Sequence[str],
    scores: Sequence[float],
    categories: Sequence[str | None],
    *,
    bonus: float,
    shortlist_size: int = 100,
    limit: int = 20,
) -> tuple[int, ...]:
    """Return original candidate indices, preserving the learned Top-K at bonus zero."""
    if (
        type(shortlist_size) is not int
        or shortlist_size <= 0
        or type(limit) is not int
        or not 0 < limit <= shortlist_size
    ):
        raise ValueError("Shortlist and output limits must be positive plain integers.")
    if isinstance(bonus, bool) or not isinstance(bonus, Real) or not math.isfinite(bonus):
        raise ValueError("Category novelty bonus must be finite and nonnegative.")
    if not 0 <= bonus <= 1:
        raise ValueError("Category novelty bonus must be in [0, 1].")
    if len(item_ids) != len(scores) or len(item_ids) != len(categories):
        raise ValueError("Items, scores and categories must have the same length.")
    if any(not isinstance(item, str) or not item for item in item_ids):
        raise ValueError("Candidate item IDs must be nonempty strings.")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("Candidate item IDs must be unique.")
    if any(
        category is not None and (not isinstance(category, str) or not category)
        for category in categories
    ):
        raise ValueError("Known categories must be nonempty strings.")
    if any(isinstance(score, bool) or not isinstance(score, Real) for score in scores):
        raise ValueError("Learned scores must be finite real numbers.")
    values = np.asarray(scores, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("Learned scores must be finite real numbers.")
    if not item_ids:
        return ()

    ranked = np.lexsort((np.asarray(item_ids, dtype=str), -values))[:shortlist_size]
    take = min(limit, len(ranked))
    if bonus == 0:
        return tuple(int(index) for index in ranked[:take])

    shortlist_categories = [categories[int(index)] for index in ranked]
    base = 1.0 - np.arange(len(ranked), dtype=np.float64) / max(len(ranked) - 1, 1)
    available = np.ones(len(ranked), dtype=bool)
    selected_categories: set[str] = set()
    output: list[int] = []
    for _ in range(take):
        utility = base.copy()
        utility += bonus * np.fromiter(
            (
                category is not None and category not in selected_categories
                for category in shortlist_categories
            ),
            dtype=bool,
            count=len(ranked),
        )
        utility[~available] = -np.inf
        winner = int(np.argmax(utility))
        available[winner] = False
        category = shortlist_categories[winner]
        if category is not None:
            selected_categories.add(category)
        output.append(int(ranked[winner]))
    return tuple(output)
