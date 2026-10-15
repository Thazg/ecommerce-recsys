"""Load a verified cutoff snapshot and recommend without scripts or training data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ecommerce_recsys.artifacts.adapters import restore_sources, validate_state
from ecommerce_recsys.artifacts.contract import (
    FEATURE_NAMES,
    POLICY,
    component_record,
    digest,
    verify_inventory,
)
from ecommerce_recsys.ranking.dataset import request_id
from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator

TABLE_COLUMNS = {
    "users": ("user_id", "events", "distinct", "last", "view", "addtocart", "transaction"),
    "items": (
        "item_id",
        "events",
        "distinct",
        "last",
        "view",
        "addtocart",
        "transaction",
        "category_id",
        "recent",
    ),
    "affinities": ("user_id", "category_id", "count"),
    "neighbors": ("item_id", "neighbor_id", "similarity", "support"),
}


def feature_matrix(rows: list[dict]) -> np.ndarray:
    """Inference-only implementation of the published ordered feature transform."""
    if not rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    columns = []
    for name in FEATURE_NAMES:
        values = np.array([row[name] for row in rows], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite predictor: {name}")
        if name == "retrieval_rank" or name.endswith("_rank"):
            if (values < 1).any():
                raise ValueError("Feature ranks must be positive.")
            values = 1.0 / (60.0 + values)
        elif name.endswith("_count") or name.endswith("_days_since_last_event"):
            if (values < 0).any():
                raise ValueError("Feature counts and ages must be nonnegative.")
            values = np.log1p(values)
        elif name.endswith("_score") and name != "rrf_score":
            values = np.sign(values) * np.log1p(np.abs(values))
        elif name.endswith("_present") or name == "category_known":
            if not np.isin(values, (0, 1)).all():
                raise ValueError("Feature indicators must be binary.")
        columns.append(values)
    return np.column_stack(columns)


@dataclass(frozen=True, slots=True)
class Recommendation:
    items: tuple[str, ...]
    route: str
    bundle_version: str
    cutoff: int


class LoadedBundle:
    """Read-only snapshot lookup. Unknown/absent users take the explicit cold route.

    Numerical calls use one thread. threadpoolctl changes process-wide limits;
    this adapter has not been validated for concurrent HTTP request execution.
    """

    def __init__(self, manifest, tables, arrays):
        self.manifest = manifest
        self.arrays = arrays
        sources, self.features, self.user_index, self.users, self.items = restore_sources(
            tables, arrays, manifest["snapshot"]["configs"], manifest["snapshot"]["cutoff"]
        )
        self.hybrid = HybridCandidateGenerator(
            sources, pool_size=POLICY["candidate_budget"], rank_constant=POLICY["rrf_constant"]
        )
        self.cold = next(source for source in sources if source.name == POLICY["cold"])

    def context(self, user_id: str | int | None) -> RetrievalContext:
        if user_id is not None:
            if type(user_id) not in (str, int) or not str(user_id).strip():
                raise ValueError("User ID must be a nonempty string, integer or None.")
            user_id = str(user_id)
        index = self.user_index.get(user_id)
        if index is None:
            return RetrievalContext(user_id=user_id)
        start, end = self.arrays["seen_indptr"][index : index + 2]
        return RetrievalContext(
            user_id=user_id,
            history=tuple(self.items[i] for i in self.arrays["seen_indices"][start:end]),
        )

    def trace(self, user_id: str | int | None) -> dict:
        """Label-free diagnostic trace used for producer/loader parity checks."""
        with threadpool_limits(limits=1):
            context = self.context(user_id)
            warm = context.user_id in self.user_index
            pool = (self.hybrid if warm else self.cold).generate(
                context, POLICY["candidate_budget"]
            )
            rows = []
            if warm:
                seen = frozenset(context.history)
                key = request_id(self.manifest["snapshot"]["fold_index"], context.user_id)
                rows = [
                    self.features.candidate_row(
                        fold_index=self.manifest["snapshot"]["fold_index"],
                        context=context,
                        candidate=candidate,
                        rank=rank,
                        target_item_id="",
                        request_key=key,
                        seen_items=seen,
                    )
                    for rank, candidate in enumerate(pool, 1)
                ]
            matrix = feature_matrix(rows)
            scores = (matrix / self.arrays["scales"]) @ self.arrays["weights"]
            if not np.isfinite(scores).all():
                raise ValueError("Ranker produced a nonfinite score.")
            ids = [candidate.item_id for candidate in pool]
            order = np.lexsort((np.array(ids), -scores)) if warm else np.arange(len(ids))
            return {
                "pool": ids,
                "output": [ids[i] for i in order[: POLICY["output_limit"]]],
                "evidence_sha256": evidence_digest(pool),
                "features_sha256": array_digest(matrix),
                "scores_sha256": array_digest(scores),
                "route": POLICY["warm"] if warm else POLICY["cold"],
            }

    def recommend(self, user_id: str | int | None = None, *, k: int = 20) -> Recommendation:
        if type(k) is not int or not 1 <= k <= POLICY["output_limit"]:
            raise ValueError("Output limit must be a plain integer between 1 and 20.")
        trace = self.trace(user_id)
        return Recommendation(
            tuple(trace["output"][:k]),
            trace["route"],
            self.manifest["bundle_version"],
            self.manifest["snapshot"]["cutoff"],
        )


def evidence_digest(pool) -> str:
    return digest(
        [
            {
                "item": candidate.item_id,
                "score": candidate.score,
                "evidence": [
                    [entry.source, entry.score, entry.rank] for entry in candidate.evidence
                ],
            }
            for candidate in pool
        ]
    )


def array_digest(array: np.ndarray) -> str:
    import hashlib

    return digest(
        {
            "shape": list(array.shape),
            "dtype": str(array.dtype),
            "data": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
        }
    )


def load_bundle(path: str | Path, *, expected_manifest_sha256: str | None = None) -> LoadedBundle:
    root = Path(path)
    manifest = verify_inventory(root, expected_manifest_sha256)
    arrays, tables = {}, {}
    for name, record in manifest["components"].items():
        # Inventory verification has already hashed every file before any load.
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
    return LoadedBundle(manifest, tables, arrays)
