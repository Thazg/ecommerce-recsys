"""Quality accounting and development selection for complete offline policies."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from numbers import Real

K_VALUES = (5, 10, 20)
CANDIDATE_BUDGET = 1000


@dataclass(frozen=True, slots=True)
class PolicySpec:
    name: str
    generator: str
    sources: tuple[str, ...]
    learned: bool = False
    bonus: float = 0.0

    def record(self) -> dict:
        return {
            "name": self.name,
            "generator": self.generator,
            "sources": list(self.sources),
            "learned": self.learned,
            "category_bonus": self.bonus,
        }


DIRECT_SOURCES = (
    "global_popularity",
    "recent_popularity",
    "category_popularity",
    "item_knn",
    "als",
)
FULL_SOURCES = ("item_knn", "als", "category_popularity", "recent_popularity", "global_popularity")
NO_ALS_SOURCES = tuple(name for name in FULL_SOURCES if name != "als")
WARM_POLICIES = (
    *(PolicySpec(name, name, (name,)) for name in DIRECT_SOURCES),
    PolicySpec("hybrid_rrf", "hybrid", FULL_SOURCES),
    PolicySpec("no_als_rrf", "hybrid_without_als", NO_ALS_SOURCES),
    PolicySpec("hybrid_learned", "hybrid", FULL_SOURCES, True),
    PolicySpec("hybrid_category", "hybrid", FULL_SOURCES, True, 0.1),
    PolicySpec("no_als_learned_transfer", "hybrid_without_als", NO_ALS_SOURCES, True),
    PolicySpec("no_als_category_transfer", "hybrid_without_als", NO_ALS_SOURCES, True, 0.1),
)
COLD_POLICIES = (
    PolicySpec("global_popularity", "global_popularity", ("global_popularity",)),
    PolicySpec("recent_popularity", "recent_popularity", ("recent_popularity",)),
    PolicySpec("popularity_rrf", "popularity_rrf", ("recent_popularity", "global_popularity")),
)


def _count(value: object, name: str, upper: int) -> int:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f"{name} must be an integer count in [0, {upper}].")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number.")
    return float(value)


@dataclass(slots=True)
class PolicyTotals:
    catalog: frozenset[str]
    categories: dict[str, str | None]
    requests: int = 0
    reachable: int = 0
    in_pool: int = 0
    candidates: int = 0
    empty_pools: int = 0
    full_pools: int = 0
    empty_outputs: int = 0
    short_outputs: int = 0
    slots: int = 0
    known_slots: int = 0
    distinct_slots: int = 0
    hits: dict[int, int] = field(default_factory=lambda: dict.fromkeys(K_VALUES, 0))
    reciprocal: dict[int, float] = field(default_factory=lambda: dict.fromkeys(K_VALUES, 0.0))
    discounted: dict[int, float] = field(default_factory=lambda: dict.fromkeys(K_VALUES, 0.0))
    unique: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if (
            not self.catalog
            or set(self.categories) != self.catalog
            or any(not isinstance(item, str) or not item for item in self.catalog)
            or any(
                category is not None and (not isinstance(category, str) or not category)
                for category in self.categories.values()
            )
        ):
            raise ValueError("Policy totals require a nonempty catalog and its category snapshot.")

    def add(
        self, pool: list[str], output: list[str], target: str, seen: frozenset[str] = frozenset()
    ) -> None:
        self.add_shared(pool, output, Counter({target: 1}), seen)

    def add_shared(
        self,
        pool: list[str],
        output: list[str],
        targets: Counter[str],
        seen: frozenset[str] = frozenset(),
    ) -> None:
        """Count a shared cold-context output exactly, without sampling its targets."""
        pool_set = set(pool)
        if (
            len(pool) > CANDIDATE_BUDGET
            or len(pool_set) != len(pool)
            or not pool_set.issubset(self.catalog)
            or pool_set.intersection(seen)
            or len(output) != min(K_VALUES[-1], len(pool))
            or len(set(output)) != len(output)
            or not set(output).issubset(pool_set)
            or any(not isinstance(item, str) or not item for item in (*pool, *targets))
            or any(type(count) is not int or count <= 0 for count in targets.values())
            or set(targets).intersection(seen)
        ):
            raise ValueError("Policy pool, output or target counts violate the request contract.")
        count = sum(targets.values())
        self.requests += count
        self.reachable += sum(value for item, value in targets.items() if item in self.catalog)
        self.in_pool += sum(targets[item] for item in pool)
        self.candidates += count * len(pool)
        self.empty_pools += count * (len(pool) == 0)
        self.full_pools += count * (len(pool) == CANDIDATE_BUDGET)
        self.empty_outputs += count * (len(output) == 0)
        self.short_outputs += count * (len(output) < K_VALUES[-1])
        self.slots += count * len(output)
        known = [self.categories[item] for item in output if self.categories[item] is not None]
        self.known_slots += count * len(known)
        self.distinct_slots += count * len(set(known))
        if count:
            self.unique.update(output)
        for rank, item in enumerate(output, start=1):
            multiplicity = targets[item]
            for k in K_VALUES:
                if rank <= k:
                    self.hits[k] += multiplicity
                    self.reciprocal[k] += multiplicity / rank
                    self.discounted[k] += multiplicity / math.log2(rank + 1)

    def output(self) -> dict:
        result = {
            "requests": self.requests,
            "reachable_targets": self.reachable,
            "target_in_pool": self.in_pool,
            "candidate_count": self.candidates,
            "empty_pools": self.empty_pools,
            "full_pools": self.full_pools,
            "empty_outputs": self.empty_outputs,
            "short_outputs": self.short_outputs,
            "recommendation_slots": self.slots,
            "known_category_item_slots": self.known_slots,
            "distinct_known_category_slots": self.distinct_slots,
            "unique_items": len(self.unique),
            "hits": {str(k): self.hits[k] for k in K_VALUES},
            "reciprocal_sum": {str(k): self.reciprocal[k] for k in K_VALUES},
            "discounted_sum": {str(k): self.discounted[k] for k in K_VALUES},
        }
        result.update(derived_metrics(result, len(self.catalog)))
        return result


def derived_metrics(result: dict, catalog_size: int) -> dict[str, float]:
    denominator = result["requests"] or 1
    slots = K_VALUES[-1] * denominator
    metrics = {
        "candidate_recall@1000": result["target_in_pool"] / denominator,
        "reachable_candidate_recall@1000": result["target_in_pool"]
        / (result["reachable_targets"] or 1),
        "empty_pool_rate": result["empty_pools"] / denominator,
        "full_pool_rate": result["full_pools"] / denominator,
        "empty_output_rate": result["empty_outputs"] / denominator,
        "short_output_rate": result["short_outputs"] / denominator,
        "mean_candidates": result["candidate_count"] / denominator,
        "known_category_item_slots@20": result["known_category_item_slots"] / slots,
        "distinct_known_category_slots@20": result["distinct_known_category_slots"] / slots,
        "item_coverage@20": result["unique_items"] / catalog_size,
    }
    for k in K_VALUES:
        for metric, field_name in (
            ("HR", "hits"),
            ("MRR", "reciprocal_sum"),
            ("NDCG", "discounted_sum"),
        ):
            metrics[f"{metric}@{k}"] = result[field_name][str(k)] / denominator
    return metrics


def validate_result(result: dict, *, requests: int, catalog_size: int) -> None:
    """Reject malformed counts and rates even when a JSON checksum was regenerated."""
    _count(catalog_size, "Catalog size", 10**9)
    if not catalog_size or result["requests"] != requests:
        raise ValueError("Policy result population differs from the fold.")
    _count(result["requests"], "Requests", 10**9)
    reachable = _count(result["reachable_targets"], "Reachable targets", requests)
    in_pool = _count(result["target_in_pool"], "Targets in pool", reachable)
    candidates = _count(result["candidate_count"], "Candidates", requests * CANDIDATE_BUDGET)
    empty = _count(result["empty_pools"], "Empty pools", requests)
    full = _count(result["full_pools"], "Full pools", requests - empty)
    if candidates < (requests - empty) + full * (CANDIDATE_BUDGET - 1):
        raise ValueError("Candidate counts cannot fill the declared nonempty/full pools.")
    if candidates > CANDIDATE_BUDGET * (requests - empty):
        raise ValueError("Candidate counts exceed nonempty pool capacity.")
    if _count(result["empty_outputs"], "Empty outputs", requests) != empty:
        raise ValueError("Empty output counts differ from empty pools.")
    short = _count(result["short_outputs"], "Short outputs", requests)
    slots = _count(result["recommendation_slots"], "Output slots", 20 * requests)
    if short < empty or not 20 * (requests - short) <= slots <= 20 * requests - short - 19 * empty:
        raise ValueError("Output slots differ from short/empty output counts.")
    known = _count(result["known_category_item_slots"], "Known category slots", slots)
    _count(result["distinct_known_category_slots"], "Distinct category slots", known)
    _count(result["unique_items"], "Unique items", min(catalog_size, slots))
    previous = 0
    previous_reciprocal = previous_discounted = 0.0
    for k in K_VALUES:
        hits = _count(result["hits"][str(k)], "Hits", in_pool)
        reciprocal = _finite(result["reciprocal_sum"][str(k)], "Reciprocal sum")
        discounted = _finite(result["discounted_sum"][str(k)], "Discounted sum")
        if (
            hits < previous
            or reciprocal + 1e-9 < previous_reciprocal
            or discounted + 1e-9 < previous_discounted
            or not hits / k - 1e-9 <= reciprocal <= discounted + 1e-9 <= hits + 2e-9
            or discounted < hits / math.log2(k + 1) - 1e-9
        ):
            raise ValueError("Policy rank numerators are outside valid bounds.")
        previous = hits
        previous_reciprocal, previous_discounted = reciprocal, discounted
    for name, expected in derived_metrics(result, catalog_size).items():
        if not math.isclose(_finite(result[name], name), expected, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Policy derived metric differs from its integer/rank numerators.")


def pooled_results(rows: list[dict], cohort: str, name: str) -> dict:
    """Pool numerators; catalog coverage deliberately stays at fold level."""
    results = [row[cohort][name] for row in rows]
    count_fields = (
        "requests",
        "reachable_targets",
        "target_in_pool",
        "candidate_count",
        "empty_pools",
        "full_pools",
        "empty_outputs",
        "short_outputs",
        "recommendation_slots",
        "known_category_item_slots",
        "distinct_known_category_slots",
    )
    output = {key: sum(result[key] for result in results) for key in count_fields}
    for field_name in ("hits", "reciprocal_sum", "discounted_sum"):
        output[field_name] = {
            str(k): sum(result[field_name][str(k)] for result in results) for k in K_VALUES
        }
    # Catalogs change between windows; unique IDs and coverage cannot be pooled.
    metrics = derived_metrics({**output, "unique_items": 0}, 1)
    metrics.pop("item_coverage@20")
    return {**output, **metrics}


def select_routes(rows: list[dict]) -> dict[str, str]:
    if [row["fold_index"] for row in rows] != [2, 3, 4]:
        raise ValueError("Policy selection requires complete development folds 2–4.")
    selected = {}
    for cohort, specs in (("warm", WARM_POLICIES), ("cold", COLD_POLICIES)):
        if any(set(row[cohort]) != {spec.name for spec in specs} for row in rows):
            raise ValueError("Policy selection requires the complete fixed policy grid.")
        scores = {spec.name: pooled_results(rows, cohort, spec.name) for spec in specs}
        winner = min(
            specs,
            key=lambda spec: (
                -scores[spec.name]["hits"]["20"],
                -scores[spec.name]["discounted_sum"]["20"],
                len(spec.sources),
                spec.bonus,
                spec.name,
            ),
        )
        selected[cohort] = winner.name
    return selected
