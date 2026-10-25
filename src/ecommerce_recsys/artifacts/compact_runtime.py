"""Opt-in indexed snapshot state with the original validation and prediction code.

The published reader and default API loader remain unchanged. This reader keeps
feature counts in numeric arrays rather than one Python dictionary per user.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from ecommerce_recsys.artifacts.adapters import AGGREGATE_COLUMNS, validate_state
from ecommerce_recsys.artifacts.contract import POLICY, component_record, verify_inventory
from ecommerce_recsys.artifacts.runtime import TABLE_COLUMNS, LoadedBundle
from ecommerce_recsys.ranking.dataset import EVENT_TYPES, SnapshotFeatures
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.retrieval.category_retriever import CategoryRetriever
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator
from ecommerce_recsys.retrieval.item_knn_retriever import ItemKNNRetriever
from ecommerce_recsys.retrieval.mf_retriever import MFRetriever
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever


def _column(frame, name):
    values = frame[name].to_numpy(copy=True)
    values.flags.writeable = False
    return values


class _Column(Mapping):
    def __init__(self, index, values):
        self.index, self.values = index, values

    def __getitem__(self, key):
        return int(self.values[self.index[key]])

    def __iter__(self):
        return iter(self.index)

    def __len__(self):
        return len(self.index)

    def __contains__(self, key):
        return key in self.index


class _EventRow(Mapping):
    def __init__(self, columns, row):
        self.columns, self.row = columns, row

    def __getitem__(self, key):
        if key not in EVENT_TYPES:
            raise KeyError(key)
        value = int(self.columns[EVENT_TYPES.index(key)][self.row])
        if value == 0:
            raise KeyError(key)
        return value

    def __iter__(self):
        return (key for key, column in zip(EVENT_TYPES, self.columns) if column[self.row])

    def __len__(self):
        return sum(bool(column[self.row]) for column in self.columns)


class _Events(Mapping):
    def __init__(self, index, columns):
        self.index, self.columns = index, columns

    def __getitem__(self, key):
        return _EventRow(self.columns, self.index[key])

    def __iter__(self):
        return iter(self.index)

    def __len__(self):
        return len(self.index)


class _Affinities(Mapping):
    """Sparse user/category counts; lookup does not allocate tuple-key dictionaries."""

    def __init__(self, frame, users):
        self.users = users
        self.categories = tuple(sorted(set(frame["category_id"])))
        self.category_index = {value: i for i, value in enumerate(self.categories)}
        user_codes = np.fromiter((users[u] for u in frame["user_id"]), dtype=np.int64)
        category_codes = np.fromiter(
            (self.category_index[c] for c in frame["category_id"]), dtype=np.int64
        )
        order = np.lexsort((category_codes, user_codes))
        self.indices = category_codes[order]
        self.counts = frame["count"].to_numpy(copy=True)[order]
        self.indptr = np.empty(len(users) + 1, dtype=np.int64)
        self.indptr[0] = 0
        np.cumsum(np.bincount(user_codes, minlength=len(users)), out=self.indptr[1:])
        for array in (self.indices, self.counts, self.indptr):
            array.flags.writeable = False

    def __getitem__(self, key):
        if not isinstance(key, tuple) or len(key) != 2:
            raise KeyError(key)
        row, category = self.users[key[0]], self.category_index[key[1]]
        start, end = self.indptr[row : row + 2]
        offset = int(start) + int(np.searchsorted(self.indices[start:end], category))
        if offset >= end or self.indices[offset] != category:
            raise KeyError(key)
        return int(self.counts[offset])

    def __iter__(self):
        for user, row in self.users.items():
            start, end = self.indptr[row : row + 2]
            for category in self.indices[start:end]:
                yield user, self.categories[category]

    def __len__(self):
        return len(self.counts)


def _features(tables, users, items, categories, cutoff):
    def columns(frame, index):
        values = {key: _column(frame, key) for key in AGGREGATE_COLUMNS}
        return (
            *(_Column(index, values[key]) for key in ("events", "distinct", "last")),
            _Events(index, tuple(values[key] for key in EVENT_TYPES)),
        )

    return SnapshotFeatures(
        cutoff,
        categories,
        *columns(tables["users"], users),
        *columns(tables["items"], items),
        _Affinities(tables["affinities"], users),
    )


class CompactBundle(LoadedBundle):
    """Use frozen context/trace/recommend methods with indexed feature mappings."""

    def __init__(self, manifest, tables, arrays):
        self.manifest, self.arrays = manifest, arrays
        self.users = tables["users"]["user_id"].tolist()
        self.items = tables["items"]["item_id"].tolist()
        self.user_index = {user: i for i, user in enumerate(self.users)}
        item_index = {item: i for i, item in enumerate(self.items)}
        configs, cutoff = manifest["snapshot"]["configs"], manifest["snapshot"]["cutoff"]
        als = MatrixFactorizationRecommender(**configs["als"], random_state=42)
        als._model = SimpleNamespace(
            user_factors=arrays["user_factors"], item_factors=arrays["item_factors"]
        )
        als._index_to_user, als._index_to_item = self.users, self.items
        als._user_to_index, als._item_to_index = self.user_index, item_index
        als._user_item_matrix = csr_matrix(
            (
                np.ones(len(arrays["seen_indices"]), dtype=np.uint8),
                arrays["seen_indices"],
                arrays["seen_indptr"],
            ),
            shape=(len(self.users), len(self.items)),
        )
        ranking = sorted(
            zip(self.items, tables["items"]["events"].astype(float), strict=True),
            key=lambda row: (-row[1], row[0]),
        )
        knn = ItemKNNRecommender(n_neighbors=20, min_item_interactions=5, **configs["item_knn"])
        knn._item_neighbors = {item: [] for item in self.items}
        # The frozen direct scorer checks this fitted-state marker, without
        # invoking fallback for an empty candidate pool.
        knn._fallback_recommender = PopularityRecommender()
        knn._fallback_recommender._ranking = [item for item, _ in ranking]
        for row in tables["neighbors"].itertuples(index=False):
            item, neighbor = (
                self.items[item_index[row.item_id]],
                self.items[item_index[row.neighbor_id]],
            )
            knn._item_neighbors[item].append((neighbor, row.similarity, row.support))
        empty = pd.DataFrame({"item_id": pd.Series(dtype=str)})
        category = CategoryRetriever(empty, tables["items"][["item_id", "category_id"]])
        for item, count in ranking:
            if item in category.categories:
                category.rankings.setdefault(category.categories[item], []).append((item, count))
        global_source = PopularityRetriever(empty, self.items)
        global_source.ranking = tuple(ranking)
        recent = PopularityRetriever(empty, self.items)
        recent.name = "recent_popularity"
        recent.ranking = tuple(
            sorted(
                [
                    (item, float(count))
                    for item, count in zip(self.items, tables["items"]["recent"], strict=True)
                    if count > 0
                ],
                key=lambda row: (-row[1], row[0]),
            )
        )
        sources = [
            ItemKNNRetriever(knn, self.items),
            MFRetriever(als, self.items),
            category,
            recent,
            global_source,
        ]
        self.features = _features(tables, self.user_index, item_index, category.categories, cutoff)
        self.hybrid = HybridCandidateGenerator(
            sources, pool_size=POLICY["candidate_budget"], rank_constant=POLICY["rrf_constant"]
        )
        for source in sources:
            source.catalog = self.hybrid.catalog
        self.cold = recent


def load_compact_bundle(path: str | Path, *, expected_manifest_sha256: str) -> CompactBundle:
    """Verify the unchanged bundle before constructing opt-in compact state."""
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch(
        "[0-9a-f]{64}", expected_manifest_sha256
    ):
        raise ValueError("Compact loading requires an external lowercase manifest SHA-256.")
    root = Path(path)
    manifest = verify_inventory(root, expected_manifest_sha256)
    arrays, tables = {}, {}
    for name, record in manifest["components"].items():
        if component_record(root / name, include_hash=False) != {
            key: value for key, value in record.items() if key != "sha256"
        }:
            raise ValueError(f"Component schema/shape differs: {name}")
        if name.endswith(".npy"):
            arrays[Path(name).stem] = np.load(root / name, mmap_mode="r", allow_pickle=False)
        elif name.endswith(".parquet"):
            key = Path(name).stem
            tables[key] = pd.read_parquet(root / name)
            if (
                tuple(tables[key].columns) != TABLE_COLUMNS[key]
                or tables[key]
                .drop(columns=["category_id"] if key == "items" else [])
                .isna()
                .any()
                .any()
            ):
                raise ValueError(f"Component columns or null fields are invalid: {name}")
    validate_state(tables, arrays, manifest["snapshot"])
    return CompactBundle(manifest, tables, arrays)
