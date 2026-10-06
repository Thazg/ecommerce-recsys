"""Candidate recall and availability, independent of final ranking metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from time import perf_counter

import pandas as pd

from ecommerce_recsys.data.splitting import (
    verify_global_train_before_target,
    verify_unseen_targets,
)
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.retrieval.base import Candidate, CandidateGenerator, RetrievalContext
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator

N_VALUES = (100, 500, 1000)


class CandidateMetrics:
    """Accumulate exact hit/count totals so pooled rates need no rounded inputs."""

    def __init__(self, catalog: frozenset[str], n_values: tuple[int, ...] = N_VALUES) -> None:
        if not n_values or any(n <= 0 for n in n_values) or sorted(set(n_values)) != list(n_values):
            raise ValueError(
                "Candidate cutoffs must be unique positive integers in increasing order."
            )
        self.catalog = catalog
        self.n_values = n_values
        self.users = 0
        self.reachable = 0
        self.hits = Counter()
        self.counts = Counter()
        self.empty = Counter()
        self.full = Counter()
        self.coverage = {n: set() for n in n_values}
        self.source_counts = {n: Counter() for n in n_values}
        self.source_hits = {n: Counter() for n in n_values}
        self.exclusive_hits = {n: Counter() for n in n_values}

    def add(self, target: str, candidates: list[Candidate], weight: int = 1) -> None:
        if weight <= 0:
            raise ValueError("Evaluation weight must be positive.")
        target = str(target)
        self.users += weight
        self.reachable += weight * (target in self.catalog)
        item_ids = [candidate.item_id for candidate in candidates]
        try:
            target_rank = item_ids.index(target) + 1
            target_candidate = candidates[target_rank - 1]
        except ValueError:
            target_rank, target_candidate = 0, None
        source_counts: Counter[str] = Counter()
        previous = 0
        for n in self.n_values:
            pool = candidates[:n]
            self.coverage[n].update(item_ids[:n])
            source_counts.update(
                entry.source for candidate in pool[previous:] for entry in candidate.evidence
            )
            self.source_counts[n].update({s: count * weight for s, count in source_counts.items()})
            hit = target_candidate is not None and target_rank <= n
            self.hits[n] += weight * hit
            self.counts[n] += weight * len(pool)
            self.empty[n] += weight * (not pool)
            self.full[n] += weight * (len(pool) == n)
            if hit:
                sources = [entry.source for entry in target_candidate.evidence]
                self.source_hits[n].update({source: weight for source in sources})
                if len(sources) == 1:
                    self.exclusive_hits[n][sources[0]] += weight
            previous = len(pool)

    def output(self) -> dict:
        rates = {}
        totals = {}
        for n in self.n_values:
            denom = self.users or 1
            rates[f"Recall@{n}"] = self.hits[n] / denom
            rates[f"reachable_recall@{n}"] = (
                self.hits[n] / self.reachable if self.reachable else 0.0
            )
            rates[f"mean_candidates@{n}"] = self.counts[n] / denom
            rates[f"empty_rate@{n}"] = self.empty[n] / denom
            rates[f"full_rate@{n}"] = self.full[n] / denom
            rates[f"coverage@{n}"] = len(self.coverage[n]) / (len(self.catalog) or 1)
            totals[str(n)] = {
                "hits": self.hits[n],
                "candidate_count": self.counts[n],
                "empty_requests": self.empty[n],
                "full_requests": self.full[n],
                "unique_items": len(self.coverage[n]),
                "source_candidate_count": dict(self.source_counts[n]),
                "source_target_hits": dict(self.source_hits[n]),
                "exclusive_source_target_hits": dict(self.exclusive_hits[n]),
            }
        return {
            "evaluation_users": self.users,
            "reachable_targets": self.reachable,
            "metrics": rates,
            "totals": totals,
        }

    def add_shared(self, target_counts: dict[str, int], candidates: list[Candidate]) -> None:
        """Evaluate a shared cold pool without repeating identical request work."""
        if self.users:
            raise ValueError("Shared-pool evaluation requires a fresh accumulator.")
        self.users = sum(target_counts.values())
        self.reachable = sum(count for item, count in target_counts.items() if item in self.catalog)
        for n in self.n_values:
            pool = candidates[:n]
            self.counts[n] = self.users * len(pool)
            self.empty[n] = self.users * (not pool)
            self.full[n] = self.users * (len(pool) == n)
            self.coverage[n].update(c.item_id for c in pool if self.users)
            for candidate in pool:
                weight = target_counts.get(candidate.item_id, 0)
                self.hits[n] += weight
                for entry in candidate.evidence:
                    self.source_counts[n][entry.source] += self.users
                    self.source_hits[n][entry.source] += weight
                if len(candidate.evidence) == 1:
                    self.exclusive_hits[n][candidate.evidence[0].source] += weight


def retrieve_pools(
    sources: Sequence[CandidateGenerator],
    hybrids: Sequence[HybridCandidateGenerator],
    context: RetrievalContext,
    limit: int,
) -> tuple[dict[str, list[Candidate]], dict[str, float]]:
    pools, seconds = {}, {}
    for source in sources:
        started = perf_counter()
        pools[source.name] = source.generate(context, limit)
        seconds[source.name] = perf_counter() - started
    for hybrid in hybrids:
        started = perf_counter()
        pools[hybrid.name] = hybrid.fuse(
            {source.name: pools[source.name] for source in hybrid.sources}, context, limit
        )
        seconds[hybrid.name] = (
            perf_counter() - started + sum(seconds[source.name] for source in hybrid.sources)
        )
    return pools, seconds


def validate_targets(train: pd.DataFrame, targets: pd.DataFrame, cohort: str) -> None:
    if cohort not in {"warm", "cold"}:
        raise ValueError("Expected warm or cold cohort.")
    required = {"user_id", "item_id", "timestamp"}
    if not required.issubset(targets.columns) or not required.issubset(train.columns):
        raise ValueError("Train and targets require user_id, item_id and timestamp.")
    if targets[list(required)].isna().any().any() or train[list(required)].isna().any().any():
        raise ValueError("Train and target IDs/timestamps must not be null.")
    if targets["user_id"].astype(str).duplicated().any():
        raise ValueError("Evaluation requires one target per user in each fold.")
    if not targets.empty:
        normalized_train = train[list(required)].assign(
            user_id=train["user_id"].astype(str), item_id=train["item_id"].astype(str)
        )
        normalized_targets = targets[list(required)].assign(
            user_id=targets["user_id"].astype(str), item_id=targets["item_id"].astype(str)
        )
        verify_global_train_before_target(normalized_train, normalized_targets)
        verify_unseen_targets(normalized_train, normalized_targets)
        known = targets["user_id"].astype(str).isin(train["user_id"].astype(str))
        if (cohort == "warm" and not known.all()) or (cohort == "cold" and known.any()):
            raise ValueError(f"Targets do not belong to the {cohort} cohort.")


def evaluate_candidate_sources(
    train: pd.DataFrame,
    targets: pd.DataFrame,
    sources: Sequence[CandidateGenerator],
    hybrids: Sequence[HybridCandidateGenerator],
    *,
    cohort: str,
    n_values: tuple[int, ...] = N_VALUES,
    cold_latency_samples: int = 100,
) -> list[dict]:
    validate_targets(train, targets, cohort)
    generators = [*sources, *hybrids]
    names = [source.name for source in generators]
    if not sources or len(set(names)) != len(names):
        raise ValueError("Evaluation needs uniquely named generators.")
    catalog = sources[0].catalog
    if any(source.catalog != catalog for source in generators):
        raise ValueError("Evaluated generators must share the same catalog.")
    if cold_latency_samples <= 0:
        raise ValueError("Cold latency sample count must be positive.")
    metrics = {name: CandidateMetrics(catalog, n_values) for name in names}
    latencies: dict[str, list[float]] = {name: [] for name in names}
    limit = max(n_values)
    if cohort == "cold":
        context = RetrievalContext()
        pools, _ = retrieve_pools(sources, hybrids, context, limit)
        target_counts = {
            item: int(count)
            for item, count in targets["item_id"].astype(str).value_counts().items()
        }
        for name in names:
            metrics[name].add_shared(target_counts, pools[name])
        if not targets.empty:
            for _ in range(cold_latency_samples):
                _, seconds = retrieve_pools(sources, hybrids, context, limit)
                for name in names:
                    latencies[name].append(seconds[name])
    else:
        ids = set(targets["user_id"].astype(str))
        history_rows = train.loc[train["user_id"].astype(str).isin(ids)].copy()
        history_rows["user_id"] = history_rows["user_id"].astype(str)
        histories = {
            user: tuple(group["item_id"].astype(str))
            for user, group in history_rows.groupby("user_id", sort=False)
        }
        for index, row in enumerate(targets.itertuples(index=False), start=1):
            context = RetrievalContext(str(row.user_id), histories[str(row.user_id)])
            pools, seconds = retrieve_pools(sources, hybrids, context, limit)
            for name in names:
                metrics[name].add(str(row.item_id), pools[name])
                latencies[name].append(seconds[name])
            if index % 2000 == 0:
                print(f"    warm requests: {index:,}/{len(targets):,}", flush=True)
    return [
        {
            "generator": name,
            "cohort": cohort,
            **metrics[name].output(),
            **latency_metrics(latencies[name]),
            "latency_scope": (
                "empty-context repeated sample" if cohort == "cold" else "all warm requests"
            ),
            "latency_pool_size": limit,
            "latency_estimator": (
                "sum of source call times plus fusion"
                if name in {hybrid.name for hybrid in hybrids}
                else "direct source call"
            ),
        }
        for name in names
    ]


def summarize_candidates(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(f"{row['cohort']}/{row['generator']}", []).append(row)
    output = {}
    for key, group in grouped.items():
        users = sum(row["evaluation_users"] for row in group)
        reachable = sum(row["reachable_targets"] for row in group)
        pooled = {}
        for n in group[0]["totals"]:
            hits = sum(row["totals"][n]["hits"] for row in group)
            pooled[f"Recall@{n}"] = hits / users if users else 0.0
            pooled[f"reachable_recall@{n}"] = hits / reachable if reachable else 0.0
            for field, metric in (
                ("candidate_count", "mean_candidates"),
                ("empty_requests", "empty_rate"),
                ("full_requests", "full_rate"),
            ):
                total = sum(row["totals"][n][field] for row in group)
                pooled[f"{metric}@{n}"] = total / users if users else 0.0
        output[key] = {
            "folds": [row["fold_index"] for row in group],
            "user_window_targets": users,
            "reachable_targets": reachable,
            "pooled_metrics": pooled,
        }
    return output
