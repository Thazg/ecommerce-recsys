"""Compatibility boundary for the frozen offline source and feature implementations.

Only direct candidate methods are exposed by the runtime. Restored recommender
instances are not standalone fitted implicit models and must not be used to fit.
"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from ecommerce_recsys.ranking.dataset import EVENT_TYPES, SnapshotFeatures
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.retrieval.category_retriever import CategoryRetriever
from ecommerce_recsys.retrieval.item_knn_retriever import ItemKNNRetriever
from ecommerce_recsys.retrieval.mf_retriever import MFRetriever
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever

AGGREGATE_COLUMNS = ("events", "distinct", "last", *EVENT_TYPES)


def restore_sources(tables: dict, arrays: dict, configs: dict, cutoff: int):
    users = tables["users"]["user_id"].tolist()
    items = tables["items"]["item_id"].tolist()
    index = {item: i for i, item in enumerate(items)}
    als = MatrixFactorizationRecommender(**configs["als"], random_state=42)
    als._model = SimpleNamespace(
        user_factors=arrays["user_factors"], item_factors=arrays["item_factors"]
    )
    als._index_to_user, als._index_to_item = users, items
    als._user_to_index, als._item_to_index = {u: i for i, u in enumerate(users)}, index
    als._user_item_matrix = csr_matrix(
        (
            np.ones(len(arrays["seen_indices"]), dtype=np.uint8),
            arrays["seen_indices"],
            arrays["seen_indptr"],
        ),
        shape=(len(users), len(items)),
    )
    global_ranking = sorted(
        zip(items, tables["items"]["events"].astype(float), strict=True),
        key=lambda row: (-row[1], row[0]),
    )
    knn = ItemKNNRecommender(n_neighbors=20, min_item_interactions=5, **configs["item_knn"])
    knn._item_neighbors = {item: [] for item in items}
    for row in tables["neighbors"].itertuples(index=False):
        knn._item_neighbors[row.item_id].append((row.neighbor_id, row.similarity, row.support))
    knn._fallback_recommender = PopularityRecommender()
    knn._fallback_recommender._ranking = [item for item, _ in global_ranking]
    empty = pd.DataFrame({"item_id": pd.Series(dtype=str)})
    category = CategoryRetriever(empty, tables["items"][["item_id", "category_id"]])
    for item, count in global_ranking:
        if item in category.categories:
            category.rankings.setdefault(category.categories[item], []).append((item, count))
    global_source = PopularityRetriever(empty, items)
    global_source.ranking = tuple(global_ranking)
    recent = PopularityRetriever(empty, items)
    recent.name = "recent_popularity"
    recent.ranking = tuple(
        sorted(
            [
                (item, float(count))
                for item, count in zip(items, tables["items"]["recent"], strict=True)
                if count > 0
            ],
            key=lambda row: (-row[1], row[0]),
        )
    )
    user_frame = tables["users"].set_index("user_id")
    item_frame = tables["items"].set_index("item_id")

    def values(frame, name):
        return {key: int(value) for key, value in frame[name].items()}

    def types(frame):
        return {
            identifier: {
                event: int(count) for event, count in zip(EVENT_TYPES, row, strict=True) if count
            }
            for identifier, row in zip(
                frame.index,
                frame[list(EVENT_TYPES)].itertuples(index=False, name=None),
                strict=True,
            )
        }

    features = SnapshotFeatures(
        cutoff,
        category.categories,
        values(user_frame, "events"),
        values(user_frame, "distinct"),
        values(user_frame, "last"),
        types(user_frame),
        values(item_frame, "events"),
        values(item_frame, "distinct"),
        values(item_frame, "last"),
        types(item_frame),
        {
            (row.user_id, row.category_id): row.count
            for row in tables["affinities"].itertuples(index=False)
        },
    )
    return (
        [ItemKNNRetriever(knn, items), MFRetriever(als, items), category, recent, global_source],
        features,
        als._user_to_index,
        users,
        items,
    )


def validate_state(tables: dict, arrays: dict, snapshot: dict) -> None:
    """Validate semantics independently of file hashes supplied by a producer."""
    users, items = tables["users"], tables["items"]
    for frame, key, expected in (
        (users, "user_id", snapshot["users"]),
        (items, "item_id", snapshot["items"]),
    ):
        ids = frame[key].tolist()
        if (
            len(ids) != expected
            or any(not isinstance(x, str) or not x for x in ids)
            or ids != sorted(set(ids))
        ):
            raise ValueError("Snapshot ID mappings must be sorted, unique, nonempty strings.")
        for column in AGGREGATE_COLUMNS:
            values = frame[column].to_numpy()
            minimum = 0 if column in EVENT_TYPES else 1
            if values.dtype.kind not in "iu" or (values < minimum).any():
                raise ValueError(
                    "Feature aggregates require nonnegative integer counts/timestamps."
                )
        if (
            (frame["last"] > snapshot["cutoff"]).any()
            or (frame["distinct"] > frame["events"]).any()
            or not np.array_equal(frame[list(EVENT_TYPES)].sum(axis=1), frame["events"])
            or int(frame["events"].sum()) != snapshot["events"]
        ):
            raise ValueError("Feature aggregate counts or as-of times are inconsistent.")
    if (
        items["recent"].dtype.kind not in "iu"
        or (items["recent"] < 0).any()
        or (items["recent"] > items["events"]).any()
        or any(
            value is not None and (not isinstance(value, str) or not value)
            for value in items["category_id"]
        )
    ):
        raise ValueError("Recent counts or category IDs are invalid.")
    user_ids, item_ids = set(users["user_id"]), set(items["item_id"])
    categories = set(items["category_id"].dropna())
    affinities = tables["affinities"]
    if (
        affinities[["user_id", "category_id"]].isna().any().any()
        or affinities.duplicated(["user_id", "category_id"]).any()
        or not set(affinities["user_id"]).issubset(user_ids)
        or not set(affinities["category_id"]).issubset(categories)
        or affinities["count"].dtype.kind not in "iu"
        or (affinities["count"] <= 0).any()
    ):
        raise ValueError("User/category feature affinities are invalid.")
    totals = affinities.groupby("user_id")["count"].sum()
    if (
        totals.to_numpy() > users.set_index("user_id").loc[totals.index, "events"].to_numpy()
    ).any():
        raise ValueError("Category affinity counts exceed user event counts.")
    neighbors = tables["neighbors"]
    if (
        not set(neighbors["item_id"]).issubset(item_ids)
        or not set(neighbors["neighbor_id"]).issubset(item_ids)
        or neighbors.duplicated(["item_id", "neighbor_id"]).any()
        or (neighbors["item_id"] == neighbors["neighbor_id"]).any()
        or neighbors["support"].dtype.kind not in "iu"
        or (neighbors["support"] < 1).any()
        or not np.isfinite(neighbors["similarity"]).all()
        or not neighbors["similarity"].between(0, 1 + 1e-12).all()
        or neighbors.groupby("item_id").size().gt(20).any()
    ):
        raise ValueError("ItemKNN neighbor state is invalid.")
    indptr, indices = arrays["seen_indptr"], arrays["seen_indices"]
    if (
        indptr.ndim != 1
        or indices.ndim != 1
        or indptr.dtype.kind != "i"
        or indices.dtype.kind != "i"
        or len(indptr) != len(users) + 1
        or indptr[0] != 0
        or indptr[-1] != len(indices)
        or (np.diff(indptr) <= 0).any()
        or (indices < 0).any()
        or (indices >= len(items)).any()
        or not np.array_equal(np.diff(indptr), users["distinct"].to_numpy())
    ):
        raise ValueError("Sparse seen history shape or row counts differ from user mappings.")
    # A repeated/unsorted item within a row would silently change seen semantics.
    boundaries = np.zeros(len(indices), dtype=bool)
    boundaries[indptr[:-1]] = True
    if ((np.diff(indices) <= 0) & ~boundaries[1:]).any():
        raise ValueError("Sparse seen history rows must be unique and sorted.")
    if not np.array_equal(np.bincount(indices, minlength=len(items)), items["distinct"]):
        raise ValueError("Sparse seen history differs from item user counts.")
    dimension = snapshot["configs"]["als"]["factors"]
    for name, shape, dtype in (
        ("user_factors", (len(users), dimension), "float32"),
        ("item_factors", (len(items), dimension), "float32"),
        ("weights", (32,), "float64"),
        ("scales", (32,), "float64"),
    ):
        array = arrays[name]
        if array.shape != shape or str(array.dtype) != dtype:
            raise ValueError(f"Invalid array shape or dtype: {name}")
        for start in range(0, len(array), 100_000):
            if not np.isfinite(array[start : start + 100_000]).all():
                raise ValueError(f"Nonfinite array: {name}")
    if (arrays["scales"] <= 0).any():
        raise ValueError("Ranker scales must be positive.")


def capture_tables(sources, features, als) -> dict:
    """Serialize inference sufficient statistics in the original ALS mapping order."""

    def aggregate(ids, events, distinct, last, types, key):
        return pd.DataFrame(
            {
                key: ids,
                "events": [events[x] for x in ids],
                "distinct": [distinct[x] for x in ids],
                "last": [last[x] for x in ids],
                **{event: [types.get(x, {}).get(event, 0) for x in ids] for event in EVENT_TYPES},
            }
        )

    users = aggregate(
        als._index_to_user,
        features.user_events,
        features.user_distinct,
        features.user_last,
        features.user_types,
        "user_id",
    )
    items = aggregate(
        als._index_to_item,
        features.item_events,
        features.item_users,
        features.item_last,
        features.item_types,
        "item_id",
    )
    items["category_id"] = [features.categories.get(item) for item in items["item_id"]]
    recent = dict(sources["recent_popularity"].ranking)
    items["recent"] = [int(recent.get(item, 0)) for item in items["item_id"]]
    affinities = pd.DataFrame(
        [(u, c, count) for (u, c), count in sorted(features.user_categories.items())],
        columns=["user_id", "category_id", "count"],
    ).astype({"user_id": "string", "category_id": "string", "count": "int64"})
    neighbors = defaultdict(list)
    for item, entries in sorted(sources["item_knn"].model._item_neighbors.items()):
        for neighbor, similarity, support in entries:
            for key, value in zip(
                ("item_id", "neighbor_id", "similarity", "support"),
                (item, neighbor, similarity, support),
                strict=True,
            ):
                neighbors[key].append(value)
    neighbor_frame = pd.DataFrame(
        neighbors, columns=["item_id", "neighbor_id", "similarity", "support"]
    )
    neighbor_frame = neighbor_frame.astype(
        {
            "item_id": "string",
            "neighbor_id": "string",
            "similarity": "float64",
            "support": "int64",
        }
    )
    return {"users": users, "items": items, "affinities": affinities, "neighbors": neighbor_frame}
