"""Deterministic offline pairwise ranker and same-pool ranking metrics."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import minimize
from scipy.special import expit

if __package__:
    from scripts.build_ranking_dataset import candidate_schema
else:
    from build_ranking_dataset import candidate_schema

NON_FEATURE_COLUMNS = frozenset({"request_id", "fold_index", "item_id", "label"})
FEATURE_NAMES = tuple(name for name in candidate_schema().names if name not in NON_FEATURE_COLUMNS)
K_VALUES = (5, 10, 20)


def feature_matrix(frame: pd.DataFrame) -> np.ndarray:
    """Transform only cutoff-time predictors in their locked schema order."""
    missing = set(FEATURE_NAMES) - set(frame.columns)
    if missing:
        raise ValueError(f"Ranking predictors are missing: {sorted(missing)}")
    columns: list[np.ndarray] = []
    for name in FEATURE_NAMES:
        values = frame[name].to_numpy(dtype=np.float64, copy=True)
        if not np.isfinite(values).all():
            raise ValueError(f"Ranking predictor {name} contains nonfinite values.")
        if name == "retrieval_rank" or name.endswith("_rank"):
            if (values < 1).any():
                raise ValueError(f"Ranking predictor {name} contains an invalid rank.")
            values = 1.0 / (60.0 + values)
        elif name.endswith("_count") or name.endswith("_days_since_last_event"):
            if (values < 0).any():
                raise ValueError(f"Ranking predictor {name} contains a negative count or age.")
            values = np.log1p(values)
        elif name.endswith("_score") and name != "rrf_score":
            values = np.sign(values) * np.log1p(np.abs(values))
        elif name.endswith("_present") or name == "category_known":
            if not np.isin(values, (0.0, 1.0)).all():
                raise ValueError(f"Ranking predictor {name} must be binary.")
        columns.append(values)
    return np.column_stack(columns)


def _seed_for_request(seed: int, request_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{request_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def sample_pair_indices(
    request_id: str,
    labels: np.ndarray,
    *,
    top_negatives: int = 20,
    random_negatives: int = 80,
    seed: int = 42,
) -> tuple[int, np.ndarray] | None:
    """Keep the positive and deterministic hard/uniform negatives for one request."""
    if labels.ndim != 1 or not np.isin(labels, (0, 1)).all():
        raise ValueError("Training labels must be a one-dimensional binary array.")
    positives = np.flatnonzero(labels == 1)
    if len(positives) > 1:
        raise ValueError("A ranking request contains multiple positive candidates.")
    if len(positives) == 0:
        return None
    if top_negatives < 0 or random_negatives < 0 or top_negatives + random_negatives == 0:
        raise ValueError("Training negative budgets must be nonnegative and nonempty.")
    positive = int(positives[0])
    negatives = np.flatnonzero(labels == 0)
    if len(negatives) == 0:
        return None
    hard = negatives[:top_negatives]
    remaining = negatives[top_negatives:]
    if len(remaining) > random_negatives:
        rng = np.random.default_rng(_seed_for_request(seed, request_id))
        sampled = np.sort(rng.choice(remaining, size=random_negatives, replace=False))
    else:
        sampled = remaining
    return positive, np.concatenate((hard, sampled))


def iter_candidate_groups(path: Path, *, batch_size: int = 50_000):
    """Yield complete request groups even when a Parquet batch splits one."""
    if batch_size <= 0:
        raise ValueError("Batch size must be positive.")
    columns = ["request_id", "item_id", "label", *FEATURE_NAMES]
    parquet = pq.ParquetFile(path)
    active_id: str | None = None
    active_frames: list[pd.DataFrame] = []
    for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
        frame = batch.to_pandas()
        if frame.empty:
            continue
        ids = frame["request_id"].to_numpy()
        boundaries = np.r_[0, np.flatnonzero(ids[1:] != ids[:-1]) + 1, len(frame)]
        for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
            key = str(ids[start])
            if active_id is not None and key != active_id:
                yield active_id, pd.concat(active_frames, ignore_index=True)
                active_frames = []
            active_id = key
            active_frames.append(frame.iloc[start:end])
    if active_id is not None:
        yield active_id, pd.concat(active_frames, ignore_index=True)


@dataclass(slots=True)
class PairSample:
    differences: np.ndarray
    requests: int
    positive_requests: int
    zero_positive_requests: int
    pairs: int


def sample_training_pairs(path: Path, *, seed: int = 42, batch_size: int = 50_000) -> PairSample:
    pieces: list[np.ndarray] = []
    requests = 0
    positive_requests = 0
    zero_positive_requests = 0
    for request_id, frame in iter_candidate_groups(path, batch_size=batch_size):
        requests += 1
        labels = frame["label"].to_numpy(dtype=np.int8)
        sampled = sample_pair_indices(request_id, labels, seed=seed)
        if sampled is None:
            zero_positive_requests += 1
            continue
        positive, negatives = sampled
        features = feature_matrix(frame)
        pieces.append((features[positive] - features[negatives]).astype(np.float32))
        positive_requests += 1
    if not pieces:
        raise ValueError("Training folds contain no positive-negative ranking pairs.")
    differences = np.concatenate(pieces)
    return PairSample(
        differences=differences,
        requests=requests,
        positive_requests=positive_requests,
        zero_positive_requests=zero_positive_requests,
        pairs=len(differences),
    )


@dataclass(slots=True)
class PairwiseRanker:
    weights: np.ndarray
    scales: np.ndarray
    alpha: float
    iterations: int
    converged: bool

    @classmethod
    def fit(cls, differences: np.ndarray, *, alpha: float, max_iterations: int = 100):
        if (
            differences.ndim != 2
            or differences.shape[1] != len(FEATURE_NAMES)
            or len(differences) == 0
            or not np.isfinite(differences).all()
            or not math.isfinite(alpha)
            or alpha <= 0
            or max_iterations <= 0
        ):
            raise ValueError("Pairwise training data or optimization policy is invalid.")
        x = differences.astype(np.float64, copy=False)
        scales = np.sqrt(np.mean(x * x, axis=0))
        scales[scales < 1e-8] = 1.0
        normalized = x / scales
        count = len(normalized)

        def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
            margins = normalized @ weights
            loss = float(np.logaddexp(0.0, -margins).mean() + 0.5 * alpha * (weights @ weights))
            gradient = -(normalized.T @ expit(-margins)) / count + alpha * weights
            return loss, gradient

        result = minimize(
            objective,
            np.zeros(len(FEATURE_NAMES), dtype=np.float64),
            method="L-BFGS-B",
            jac=True,
            options={"maxiter": max_iterations, "ftol": 1e-10},
        )
        if not np.isfinite(result.x).all():
            raise ValueError("Pairwise optimizer returned nonfinite weights.")
        return cls(result.x, scales, alpha, int(result.nit), bool(result.success))

    def score(self, features: np.ndarray) -> np.ndarray:
        if features.ndim != 2 or features.shape[1] != len(FEATURE_NAMES):
            raise ValueError("Ranking score input has an incompatible feature schema.")
        scores = (features / self.scales) @ self.weights
        if not np.isfinite(scores).all():
            raise ValueError("Ranking scores must be finite.")
        return scores


def positive_rank(scores: np.ndarray, item_ids: np.ndarray, labels: np.ndarray) -> int | None:
    """Return one-based positive rank with score-descending, item-ID ties."""
    if len(scores) != len(item_ids) or len(scores) != len(labels):
        raise ValueError("Ranking arrays must align.")
    positives = np.flatnonzero(labels == 1)
    if len(positives) > 1:
        raise ValueError("Ranking request contains multiple positives.")
    if len(positives) == 0:
        return None
    index = int(positives[0])
    return 1 + int(
        np.count_nonzero(
            (scores > scores[index]) | ((scores == scores[index]) & (item_ids < item_ids[index]))
        )
    )


@dataclass(slots=True)
class RankingTotals:
    requests: int = 0
    in_pool: int = 0
    candidates: int = 0
    hits: dict[str, dict[int, int]] = field(
        default_factory=lambda: {name: {k: 0 for k in K_VALUES} for name in ("rrf", "learned")}
    )
    reciprocal: dict[str, dict[int, float]] = field(
        default_factory=lambda: {name: {k: 0.0 for k in K_VALUES} for name in ("rrf", "learned")}
    )
    discounted: dict[str, dict[int, float]] = field(
        default_factory=lambda: {name: {k: 0.0 for k in K_VALUES} for name in ("rrf", "learned")}
    )

    def add(self, *, pool_size: int, rrf_rank: int | None, learned_rank: int | None) -> None:
        if pool_size < 0 or (rrf_rank is None) != (learned_rank is None):
            raise ValueError("Ranking pool and positive ranks do not reconcile.")
        if rrf_rank is not None and not (
            1 <= rrf_rank <= pool_size and 1 <= learned_rank <= pool_size
        ):
            raise ValueError("Ranking positive rank exceeds its pool.")
        self.requests += 1
        self.candidates += pool_size
        self.in_pool += int(rrf_rank is not None)
        for name, rank in (("rrf", rrf_rank), ("learned", learned_rank)):
            if rank is None:
                continue
            for k in K_VALUES:
                if rank <= k:
                    self.hits[name][k] += 1
                    self.reciprocal[name][k] += 1.0 / rank
                    self.discounted[name][k] += 1.0 / math.log2(rank + 1)

    def as_dict(self) -> dict:
        output: dict = {
            "requests": self.requests,
            "target_in_pool": self.in_pool,
            "candidates": self.candidates,
            "candidate_recall@1000": self.in_pool / self.requests if self.requests else 0.0,
        }
        for name in ("rrf", "learned"):
            output[name] = {
                f"{metric}@{k}": value / self.requests if self.requests else 0.0
                for metric, values in (
                    ("HR", self.hits[name]),
                    ("MRR", self.reciprocal[name]),
                    ("NDCG", self.discounted[name]),
                )
                for k, value in values.items()
            }
            output[name]["hits"] = {str(k): self.hits[name][k] for k in K_VALUES}
            output[name]["conditional"] = {
                f"{metric}@{k}": value / self.in_pool if self.in_pool else 0.0
                for metric, values in (
                    ("HR", self.hits[name]),
                    ("MRR", self.reciprocal[name]),
                    ("NDCG", self.discounted[name]),
                )
                for k, value in values.items()
            }
        return output
