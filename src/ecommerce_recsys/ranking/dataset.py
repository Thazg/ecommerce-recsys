"""Build as-of-cutoff features without using future target data as predictors."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from numbers import Number

import pandas as pd

from ecommerce_recsys.retrieval.base import Candidate, RetrievalContext

SOURCE_NAMES = (
    "item_knn",
    "als",
    "category_popularity",
    "recent_popularity",
    "global_popularity",
)
EVENT_TYPES = ("view", "addtocart", "transaction")
DAY_MS = 86_400_000
CANDIDATE_BUDGET = 1000
ABSENT_SOURCE_RANK = CANDIDATE_BUDGET + 1


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be a plain integer.")
    return value


def request_id(fold_index: int, user_id: str) -> str:
    if _integer(fold_index, "Fold index") <= 0 or not isinstance(user_id, str) or not user_id:
        raise ValueError("Request identity requires a positive fold and user ID.")
    return hashlib.sha256(f"{fold_index}:{user_id}".encode("utf-8")).hexdigest()


def _counts(frame: pd.DataFrame, key: str) -> dict[str, dict[str, int]]:
    grouped = frame.groupby([key, "event_type"], sort=False).size()
    output: dict[str, dict[str, int]] = {}
    for (identifier, event_type), count in grouped.items():
        output.setdefault(str(identifier), {})[str(event_type)] = int(count)
    return output


@dataclass(slots=True)
class SnapshotFeatures:
    cutoff: int
    categories: dict[str, str]
    user_events: dict[str, int]
    user_distinct: dict[str, int]
    user_last: dict[str, int]
    user_types: dict[str, dict[str, int]]
    item_events: dict[str, int]
    item_users: dict[str, int]
    item_last: dict[str, int]
    item_types: dict[str, dict[str, int]]
    user_categories: dict[tuple[str, str], int]

    @classmethod
    def from_frames(
        cls, train: pd.DataFrame, catalog: pd.DataFrame, cutoff: int
    ) -> SnapshotFeatures:
        _integer(cutoff, "Cutoff")
        required = {"user_id", "item_id", "timestamp", "event_type"}
        if not required.issubset(train) or not {"item_id", "category_id"}.issubset(catalog):
            raise ValueError("Training interactions and catalog lack required feature fields.")
        if train.empty or train[list(required)].isna().any().any():
            raise ValueError("Training interactions must be nonempty with nonnull feature fields.")
        if catalog["item_id"].isna().any() or (train["timestamp"] > cutoff).any():
            raise ValueError("Catalog IDs must be nonnull and training events must precede cutoff.")
        if not set(train["event_type"]).issubset(EVENT_TYPES):
            raise ValueError("Unexpected training event type.")
        if catalog["item_id"].astype(str).duplicated().any():
            raise ValueError("Duplicate catalog item IDs.")
        events = train[["user_id", "item_id", "timestamp", "event_type"]].copy()
        events["user_id"] = events["user_id"].astype(str)
        events["item_id"] = events["item_id"].astype(str)
        categories = {
            str(item): str(category)
            for item, category in catalog[["item_id", "category_id"]].itertuples(index=False)
            if pd.notna(category)
        }
        user_group = events.groupby("user_id", sort=False)
        item_group = events.groupby("item_id", sort=False)
        categorized = events[["user_id", "item_id"]].copy()
        categorized["category_id"] = categorized["item_id"].map(categories)
        categorized = categorized.dropna(subset=["category_id"])
        user_categories = {
            (str(user), str(category)): int(count)
            for (user, category), count in categorized.groupby(
                ["user_id", "category_id"], sort=False
            )
            .size()
            .items()
        }
        return cls(
            cutoff=cutoff,
            categories=categories,
            user_events={str(k): int(v) for k, v in user_group.size().items()},
            user_distinct={str(k): int(v) for k, v in user_group["item_id"].nunique().items()},
            user_last={str(k): int(v) for k, v in user_group["timestamp"].max().items()},
            user_types=_counts(events, "user_id"),
            item_events={str(k): int(v) for k, v in item_group.size().items()},
            item_users={str(k): int(v) for k, v in item_group["user_id"].nunique().items()},
            item_last={str(k): int(v) for k, v in item_group["timestamp"].max().items()},
            item_types=_counts(events, "item_id"),
            user_categories=user_categories,
        )

    def candidate_row(
        self,
        *,
        fold_index: int,
        context: RetrievalContext,
        candidate: Candidate,
        rank: int,
        target_item_id: str,
        request_key: str | None = None,
        seen_items: frozenset[str] | None = None,
    ) -> dict:
        _integer(rank, "Retrieval rank")
        if (
            context.user_id is None
            or rank <= 0
            or rank > CANDIDATE_BUDGET
            or candidate.item_id in (seen_items if seen_items is not None else context.history)
        ):
            raise ValueError("Ranking candidate must have a warm user, rank and unseen item.")
        user = context.user_id
        item = candidate.item_id
        if user not in self.user_events or item not in self.item_events:
            raise ValueError("Candidate or user is absent from the training snapshot.")
        category = self.categories.get(item)
        source_evidence = {entry.source: entry for entry in candidate.evidence}
        if not source_evidence or not set(source_evidence).issubset(SOURCE_NAMES):
            raise ValueError("Candidate has unexpected source evidence.")
        row = {
            "request_id": request_key if request_key is not None else request_id(fold_index, user),
            "fold_index": fold_index,
            "item_id": item,
            "retrieval_rank": rank,
            "label": int(item == target_item_id),
            "rrf_score": float(candidate.score),
            "source_count": len(candidate.evidence),
            "user_event_count": self.user_events[user],
            "user_distinct_item_count": self.user_distinct[user],
            "user_days_since_last_event": (self.cutoff - self.user_last[user]) / DAY_MS,
            "item_event_count": self.item_events[item],
            "item_distinct_user_count": self.item_users[item],
            "item_days_since_last_event": (self.cutoff - self.item_last[item]) / DAY_MS,
            "category_known": int(category is not None),
            "user_category_event_count": (
                self.user_categories.get((user, category), 0) if category is not None else 0
            ),
        }
        for event_type in EVENT_TYPES:
            row[f"user_{event_type}_count"] = self.user_types[user].get(event_type, 0)
            row[f"item_{event_type}_count"] = self.item_types[item].get(event_type, 0)
        for source in SOURCE_NAMES:
            evidence = source_evidence.get(source)
            row[f"{source}_present"] = int(evidence is not None)
            row[f"{source}_rank"] = evidence.rank if evidence is not None else ABSENT_SOURCE_RANK
            row[f"{source}_score"] = evidence.score if evidence is not None else 0.0
        if any(isinstance(value, Number) and not math.isfinite(value) for value in row.values()):
            raise ValueError("Ranking features must be finite.")
        return row


def request_row(
    *,
    fold_index: int,
    cutoff: int,
    evaluation_cutoff: int,
    user_id: str,
    target_item_id: str,
    target_timestamp: int,
    catalog: frozenset[str],
    candidates: list[Candidate],
    request_key: str | None = None,
) -> dict:
    _integer(cutoff, "Cutoff")
    _integer(evaluation_cutoff, "Evaluation cutoff")
    _integer(target_timestamp, "Target timestamp")
    if not cutoff < target_timestamp <= evaluation_cutoff or len(candidates) > CANDIDATE_BUDGET:
        raise ValueError(
            "Target must fall after cutoff and within evaluation cutoff; pool must respect budget."
        )
    if (
        not isinstance(user_id, str)
        or not user_id
        or not isinstance(target_item_id, str)
        or not target_item_id
    ):
        raise ValueError("Request requires nonempty string user and target IDs.")
    items = [candidate.item_id for candidate in candidates]
    if len(set(items)) != len(items):
        raise ValueError("Duplicate candidate item IDs.")
    return {
        "request_id": request_key if request_key is not None else request_id(fold_index, user_id),
        "fold_index": fold_index,
        "user_id": user_id,
        "cutoff": cutoff,
        "target_item_id": target_item_id,
        "target_timestamp": target_timestamp,
        "target_in_catalog": int(target_item_id in catalog),
        "target_in_pool": int(target_item_id in items),
        "pool_size": len(items),
    }


def audit_rows(requests: list[dict], candidates: list[dict]) -> dict[str, int]:
    """Check joined row/label invariants for one streaming batch."""
    if any(type(row["label"]) is not int or row["label"] not in (0, 1) for row in candidates):
        raise ValueError("Candidate labels must be binary integers.")
    counts = Counter(row["request_id"] for row in candidates)
    positives = Counter(row["request_id"] for row in candidates if row["label"])
    if len({row["request_id"] for row in requests}) != len(requests):
        raise ValueError("Duplicate request IDs in batch.")
    for row in requests:
        key = row["request_id"]
        if counts[key] != row["pool_size"] or positives[key] != row["target_in_pool"]:
            raise ValueError("Candidate rows do not reconcile with requests.")
        if row["target_in_pool"] > row["target_in_catalog"]:
            raise ValueError("Catalog-unreachable target appears in pool.")
    if set(counts) - {row["request_id"] for row in requests}:
        raise ValueError("Candidate row without a request.")
    return {
        "requests": len(requests),
        "candidates": len(candidates),
        "positives": sum(positives.values()),
        "reachable": sum(row["target_in_catalog"] for row in requests),
        "empty": sum(row["pool_size"] == 0 for row in requests),
    }
