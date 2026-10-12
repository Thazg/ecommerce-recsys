"""Train-time next-bucket transitions for an offline sequential source experiment."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import pandas as pd

from ecommerce_recsys.retrieval.base import Candidate, SourceEvidence, validate_limit


def _events(train: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    if type(cutoff) is not int or not {"user_id", "item_id", "timestamp"}.issubset(train):
        raise ValueError(
            "Sequential events require a plain-integer cutoff and user/item/time fields."
        )
    frame = train[["user_id", "item_id", "timestamp"]]
    if (
        frame.empty
        or frame.isna().any().any()
        or not pd.api.types.is_integer_dtype(frame["timestamp"])
    ):
        raise ValueError("Sequential training events require nonnull IDs and integer timestamps.")
    if (frame["timestamp"] > cutoff).any():
        raise ValueError("Sequential training events cross the declared cutoff.")
    normalized = frame.assign(
        user_id=frame["user_id"].astype(str), item_id=frame["item_id"].astype(str)
    )
    if (normalized["user_id"] == "").any() or (normalized["item_id"] == "").any():
        raise ValueError("Sequential training IDs must be nonempty.")
    return normalized.drop_duplicates().sort_values(
        ["user_id", "timestamp", "item_id"], kind="stable"
    )


def _buckets(events: pd.DataFrame) -> Iterator[tuple[str, int, tuple[str, ...]]]:
    current_user: str | None = None
    current_time: int | None = None
    items: list[str] = []
    for user, item, timestamp in events.itertuples(index=False, name=None):
        if current_user is not None and (user != current_user or timestamp != current_time):
            assert current_time is not None
            yield current_user, current_time, tuple(items)
            items = []
        current_user = user
        current_time = int(timestamp)
        items.append(item)
    if current_user is not None:
        assert current_time is not None
        yield current_user, current_time, tuple(items)


def histories_for_users(
    train: pd.DataFrame, user_ids: Iterable[str], cutoff: int
) -> dict[str, tuple[tuple[str, ...], ...]]:
    """Preserve timestamp buckets; items within one bucket have no invented order."""
    selected = {str(user) for user in user_ids}
    if not selected or "user_id" not in train or train["user_id"].isna().any():
        raise ValueError("Sequential history requires nonempty, nonnull selected users.")
    subset = train.loc[train["user_id"].astype(str).isin(selected)]
    events = _events(subset, cutoff)
    output: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for user, _, bucket in _buckets(events):
        output[user].append(bucket)
    if set(output) != selected:
        raise ValueError("A warm evaluation user has no train-time history.")
    return {user: tuple(buckets) for user, buckets in output.items()}


@dataclass(slots=True)
class TransitionTable:
    catalog: frozenset[str]
    counts: dict[str, Counter[str]]
    outgoing: dict[str, int]
    observations: int
    distinct_pairs: int
    train_buckets: int

    @classmethod
    def fit(cls, train: pd.DataFrame, catalog: Iterable[str], cutoff: int) -> TransitionTable:
        events = _events(train, cutoff)
        values = tuple(catalog)
        if any(item is None for item in values):
            raise ValueError("Sequential catalog IDs must not be null.")
        ids = tuple(map(str, values))
        if len(ids) != len(set(ids)) or not ids or set(events["item_id"]) != set(ids):
            raise ValueError("Sequential catalog differs from training item IDs.")
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        previous_user: str | None = None
        previous_bucket: tuple[str, ...] = ()
        observations = 0
        bucket_count = 0
        for user, _, bucket in _buckets(events):
            bucket_count += 1
            if user == previous_user:
                for source in previous_bucket:
                    for destination in bucket:
                        if source != destination:
                            counts[source][destination] += 1
                            observations += 1
            previous_user, previous_bucket = user, bucket
        outgoing = {source: sum(targets.values()) for source, targets in counts.items()}
        return cls(
            frozenset(ids),
            dict(counts),
            outgoing,
            observations,
            sum(map(len, counts.values())),
            bucket_count,
        )

    def generate(
        self,
        history: tuple[tuple[str, ...], ...],
        limit: int,
        *,
        lookback: int,
        decay: float | None,
    ) -> list[Candidate]:
        """Score unseen train-catalog items with ordered or equal bucket weights."""
        validate_limit(limit)
        if type(lookback) is not int or lookback <= 0:
            raise ValueError("Sequential lookback must be a positive integer.")
        if decay is not None and (not math.isfinite(decay) or not 0 < decay < 1):
            raise ValueError("Sequential decay must be between zero and one.")
        if (
            not isinstance(history, tuple)
            or not history
            or any(
                not isinstance(bucket, tuple)
                or not bucket
                or any(not isinstance(item, str) or not item for item in bucket)
                or len(set(bucket)) != len(bucket)
                for bucket in history
            )
        ):
            raise ValueError("Sequential history requires nonempty timestamp buckets of item IDs.")
        seen = {item for bucket in history for item in bucket}
        scores: dict[str, float] = defaultdict(float)
        for age, bucket in enumerate(reversed(history[-lookback:])):
            weight = (decay**age if decay is not None else 1.0) / len(bucket)
            for source in bucket:
                total = self.outgoing.get(source, 0)
                if total:
                    for destination, count in self.counts[source].items():
                        if destination not in seen and destination in self.catalog:
                            scores[destination] += weight * count / total
        name = "sequential_ordered" if decay is not None else "sequential_equal_weight"
        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
        return [
            Candidate(item, score, (SourceEvidence(name, score, rank),))
            for rank, (item, score) in enumerate(ranked, start=1)
        ]
