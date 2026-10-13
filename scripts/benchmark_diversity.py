"""Select and measure category-aware re-ranking of the locked learned order."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from ecommerce_recsys.data.rolling_provenance import sha256_file, verify_fold_files
from ecommerce_recsys.evaluation.candidates import validate_targets
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import (
    CANDIDATE_BUDGET,
    SnapshotFeatures,
    request_id,
    request_row,
)
from ecommerce_recsys.ranking.diversity import category_novelty_order
from ecommerce_recsys.retrieval.base import RetrievalContext

if __package__:
    from scripts import benchmark_ranker as ranker
    from scripts.learned_ranker import PairwiseRanker, feature_matrix, iter_candidate_groups
else:
    import benchmark_ranker as ranker
    from learned_ranker import PairwiseRanker, feature_matrix, iter_candidate_groups


BONUSES = (0.0, 0.05, 0.10, 0.20)
K_VALUES = (5, 10, 20)
SHORTLIST = 100
POLICY = {
    "version": 1,
    "cohort": "warm first unseen target; all requests in denominator",
    "candidate_generator": "fixed M11 full-hybrid pool",
    "base_order": "locked M11 learned score descending, then item ID ascending",
    "shortlist": SHORTLIST,
    "output_budget": 20,
    "bonuses": list(BONUSES),
    "category": "train-cutoff catalog only; missing category earns no novelty bonus",
    "utility": "1 - zero-based shortlist rank / max(shortlist length - 1, 1), plus bonus for an unselected known category",
    "development_folds": [2, 3, 4],
    "diagnostic_folds": [5, 6, 7, 8, 9],
    "selection": {
        "hr_max_absolute_loss": 0.001,
        "ndcg_max_absolute_loss": 0.001,
        "known_category_slots_max_absolute_loss": 0.005,
        "objective": "strictly higher distinct known category slots, then HR hits, NDCG, smaller bonus; otherwise zero",
    },
    "numeric_threads": 1,
    "blind_holdout": False,
}
UPSTREAM_SOURCE_REVISION = "c80cebee3378ea9af7c9757802fa40e2c8594ae2"


def historical_upstream_fingerprints() -> tuple[str, str]:
    """Verify the published M10/M11 implementation despite later unrelated source additions."""
    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", UPSTREAM_SOURCE_REVISION, "src/ecommerce_recsys"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    if not listed or any(not path.endswith(".py") for path in listed):
        raise ValueError("Published upstream source revision has an invalid Python file list.")
    m10_paths = [
        *sorted(listed),
        "scripts/benchmark_candidates.py",
        "scripts/build_ranking_dataset.py",
        "scripts/prepare_rolling_data.py",
        "pyproject.toml",
    ]
    m11_paths = [
        "scripts/benchmark_ranker.py",
        "scripts/learned_ranker.py",
        "scripts/build_ranking_dataset.py",
        "scripts/benchmark_candidates.py",
        "pyproject.toml",
    ]
    unique_paths = sorted(set(m10_paths + m11_paths))
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", UPSTREAM_SOURCE_REVISION, "--", *unique_paths], cwd=root
    )
    if unchanged.returncode != 0:
        raise ValueError("Published M10/M11 source changed; frozen artifacts cannot be reused.")

    def fingerprint(paths: list[str], suffix: str = "") -> str:
        value = hashlib.sha256()
        for relative in paths:
            value.update(relative.encode("utf-8"))
            value.update((root / relative).read_bytes().replace(b"\r\n", b"\n"))
        value.update(suffix.encode("ascii"))
        return value.hexdigest()

    m10 = fingerprint(m10_paths)
    return m10, fingerprint(m11_paths, m10)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def code_fingerprint() -> str:
    """Bind this runner to the published upstream implementation, not future modules."""
    root = Path(__file__).resolve().parents[1]
    paths = (
        "scripts/benchmark_diversity.py",
        "src/ecommerce_recsys/ranking/diversity.py",
    )
    value = hashlib.sha256()
    for relative in paths:
        value.update(relative.encode("utf-8"))
        value.update((root / relative).read_bytes().replace(b"\r\n", b"\n"))
    value.update(historical_upstream_fingerprints()[1].encode("ascii"))
    return value.hexdigest()


def diagnostic_keys(selected_bonus: float) -> tuple[str, ...]:
    """Keep the control first for stable calls, timings and artifact bytes."""
    return tuple(dict.fromkeys(("0.0", str(selected_bonus))))


def write_artifact(path: Path, artifact: dict) -> None:
    artifact["payload_sha256"] = digest(
        {key: value for key, value in artifact.items() if key != "payload_sha256"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_bytes((json.dumps(artifact, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    pending.replace(path)


def read_artifact(path: Path, expected: dict) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if any(artifact.get(key) != value for key, value in expected.items()) or artifact.get(
        "payload_sha256"
    ) != digest({key: value for key, value in artifact.items() if key != "payload_sha256"}):
        raise ValueError("Diversity artifact provenance, policy or payload differs from this run.")
    return artifact


def upstream_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        input_path=args.input_path,
        fold_dir=args.fold_dir,
        manifest=args.manifest,
        sweep_dir=args.sweep_dir,
        reference=args.reference,
        m10_data_dir=args.m10_data_dir,
        m10_quality=args.m10_quality,
        development_artifact=args.ranker_development,
        selection_lock=args.ranker_lock,
        diagnostic_artifact=args.ranker_diagnostic,
    )


def inputs(args: argparse.Namespace, *, max_fold: int) -> tuple[dict, dict, dict, dict, dict, dict]:
    upstream = upstream_args(args)
    manifest, configs, ranker_identity, reference_rows = ranker.input_identity(upstream)
    verify_fold_files(manifest, args.fold_dir, max_fold)
    m10_fingerprint, m11_fingerprint = historical_upstream_fingerprints()
    quality = json.loads(args.m10_quality.read_text(encoding="utf-8"))
    if m10_fingerprint != quality.get("implementation_sha256"):
        raise ValueError("Published M10 implementation fingerprint differs from its artifact.")
    m10_expected = {
        "manifest_sha256": ranker_identity["manifest_sha256"],
        "source_sha256": ranker_identity["source_sha256"],
        "raw_property_sha256": ranker_identity["raw_property_sha256"],
        "m7_reference_sha256": ranker_identity["m7_reference_sha256"],
        "sweep_sha256": ranker_identity["sweep_sha256"],
        "model_configs": ranker_identity["model_configs"],
        "m7_policy": ranker.M7_POLICY,
        "policy": ranker.M10_POLICY,
        "feature_schema": str(ranker.candidate_schema()),
        "request_schema": str(ranker.REQUEST_SCHEMA),
        "implementation_sha256": m10_fingerprint,
    }
    ranker.validate_m10_checkpoint(quality, m10_expected, args.m10_data_dir)
    if [row["fold_index"] for row in quality["folds"]] != [1, 2, 3, 4]:
        raise ValueError("Diversity requires complete M10 development folds.")
    ranker_identity["m10_quality_sha256"] = sha256_file(args.m10_quality)
    ranker_identity["m10_data_sha256"] = quality["data_sha256"]
    ranker_identity["code_sha256"] = m11_fingerprint
    _, locked_ranker = ranker.require_development_and_lock(upstream, ranker_identity)
    if locked_ranker["selected_alpha"] != 0.01:
        raise ValueError("Diversity experiment requires the published selected ranker.")
    identity = {
        "protocol_version": "rolling-temporal",
        "manifest_sha256": ranker_identity["manifest_sha256"],
        "source_sha256": ranker_identity["source_sha256"],
        "raw_property_sha256": ranker_identity["raw_property_sha256"],
        "m7_reference_sha256": ranker_identity["m7_reference_sha256"],
        "m10_quality_sha256": sha256_file(args.m10_quality),
        "m10_data_sha256": quality["data_sha256"],
        "ranker_development_sha256": sha256_file(args.ranker_development),
        "ranker_lock_sha256": sha256_file(args.ranker_lock),
        "ranker_alpha": locked_ranker["selected_alpha"],
        "published_upstream_source_revision": UPSTREAM_SOURCE_REVISION,
        "policy": POLICY,
        "code_sha256": code_fingerprint(),
        "runtime": ranker_identity["runtime"],
    }
    return manifest, configs, identity, reference_rows, ranker_identity, quality


def category_map(catalog: pd.DataFrame, *, expected_items: int) -> dict[str, str | None]:
    if not {"item_id", "category_id"}.issubset(catalog) or catalog["item_id"].isna().any():
        raise ValueError("Diversity catalog needs nonnull item IDs and as-of categories.")
    ids = catalog["item_id"].astype(str)
    if ids.duplicated().any() or len(ids) != expected_items:
        raise ValueError("Diversity catalog has duplicate IDs or an unexpected item count.")
    return {
        item: str(category) if pd.notna(category) else None
        for item, category in zip(ids, catalog["category_id"], strict=True)
    }


@dataclass(slots=True)
class ReRankingTotals:
    catalog_size: int
    requests: int = 0
    target_in_pool: int = 0
    candidate_count: int = 0
    hits: dict[int, int] = field(default_factory=lambda: {k: 0 for k in K_VALUES})
    reciprocal: dict[int, float] = field(default_factory=lambda: {k: 0.0 for k in K_VALUES})
    discounted: dict[int, float] = field(default_factory=lambda: {k: 0.0 for k in K_VALUES})
    recommendation_slots: int = 0
    known_category_item_slots: int = 0
    distinct_known_category_slots: int = 0
    unique_items: set[str] = field(default_factory=set)

    def add(
        self,
        *,
        item_ids: list[str],
        categories: list[str | None],
        target_item: str,
        target_in_pool: bool,
        order: tuple[int, ...],
    ) -> None:
        if (
            len(item_ids) != len(categories)
            or len(order) != min(20, len(item_ids))
            or len(set(order)) != len(order)
            or any(type(index) is not int or not 0 <= index < len(item_ids) for index in order)
            or target_in_pool != (target_item in item_ids)
        ):
            raise ValueError("Re-ranking output or target availability differs from its pool.")
        self.requests += 1
        self.candidate_count += len(item_ids)
        self.target_in_pool += target_in_pool
        selected_items = [item_ids[index] for index in order]
        selected_categories = [categories[index] for index in order]
        self.recommendation_slots += len(order)
        self.known_category_item_slots += sum(
            category is not None for category in selected_categories
        )
        self.distinct_known_category_slots += len(
            {category for category in selected_categories if category is not None}
        )
        self.unique_items.update(selected_items)
        try:
            rank = selected_items.index(target_item) + 1
        except ValueError:
            rank = None
        if rank is not None:
            for k in K_VALUES:
                if rank <= k:
                    self.hits[k] += 1
                    self.reciprocal[k] += 1.0 / rank
                    self.discounted[k] += 1.0 / math.log2(rank + 1)

    def output(self) -> dict:
        denominator = self.requests or 1
        slots = 20 * denominator
        result = {
            "requests": self.requests,
            "target_in_pool": self.target_in_pool,
            "candidate_count": self.candidate_count,
            "hits": {str(k): self.hits[k] for k in K_VALUES},
            "reciprocal_sum": {str(k): self.reciprocal[k] for k in K_VALUES},
            "discounted_sum": {str(k): self.discounted[k] for k in K_VALUES},
            "recommendation_slots": self.recommendation_slots,
            "known_category_item_slots": self.known_category_item_slots,
            "distinct_known_category_slots": self.distinct_known_category_slots,
            "unique_items": len(self.unique_items),
            "known_category_item_slots@20": self.known_category_item_slots / slots,
            "distinct_known_category_slots@20": self.distinct_known_category_slots / slots,
            "item_coverage@20": len(self.unique_items) / (self.catalog_size or 1),
        }
        for k in K_VALUES:
            result[f"HR@{k}"] = self.hits[k] / denominator
            result[f"MRR@{k}"] = self.reciprocal[k] / denominator
            result[f"NDCG@{k}"] = self.discounted[k] / denominator
        return result


def check_base_parity(result: dict, upstream_metrics: dict) -> None:
    if (
        result["requests"] != upstream_metrics["requests"]
        or result["target_in_pool"] != upstream_metrics["target_in_pool"]
        or result["candidate_count"] != upstream_metrics["candidates"]
    ):
        raise ValueError("Diversity zero-bonus pool differs from the frozen ranker benchmark.")
    for k in K_VALUES:
        if result["hits"][str(k)] != upstream_metrics["learned"]["hits"][str(k)] or any(
            not math.isclose(
                result[f"{metric}@{k}"],
                upstream_metrics["learned"][f"{metric}@{k}"],
                abs_tol=1e-12,
                rel_tol=0,
            )
            for metric in ("HR", "MRR", "NDCG")
        ):
            raise ValueError("Diversity zero-bonus order differs from M11 on the same fold.")


def score_request(
    *,
    item_ids: list[str],
    scores: np.ndarray,
    categories: list[str | None],
    target_item: str,
    target_in_pool: bool,
    totals: dict[str, ReRankingTotals],
    seconds: dict[str, float],
) -> None:
    for key, accumulator in totals.items():
        started = perf_counter()
        order = category_novelty_order(
            item_ids,
            scores,
            categories,
            bonus=float(key),
            shortlist_size=SHORTLIST,
            limit=20,
        )
        seconds[key] += perf_counter() - started
        accumulator.add(
            item_ids=item_ids,
            categories=categories,
            target_item=target_item,
            target_in_pool=target_in_pool,
            order=order,
        )


def _validate_rows(rows: list[dict], manifest: dict, *, phase: str, names: set[str]) -> None:
    first, required = (2, 3) if phase == "development" else (5, 5)
    if len(rows) > required or [row.get("fold_index") for row in rows] != list(
        range(first, first + len(rows))
    ):
        raise ValueError("Diversity artifact has invalid or duplicate fold order.")
    for row in rows:
        fold = manifest["folds"][row["fold_index"] - 1]
        if (
            row.get("requests") != fold["warm_target_users"]
            or row.get("cutoff") != fold["train_cutoff"]
            or row.get("catalog_items") != fold["train_catalog_items"]
            or set(row.get("configs", {})) != names
        ):
            raise ValueError("Diversity artifact fold counts, cutoff, catalog or grid differ.")
        for result in row["configs"].values():
            if (
                result["requests"] != row["requests"]
                or not 0 <= result["target_in_pool"] <= row["requests"]
                or not 0 <= result["candidate_count"] <= CANDIDATE_BUDGET * row["requests"]
                or not 0
                <= result["distinct_known_category_slots"]
                <= result["known_category_item_slots"]
                <= result["recommendation_slots"]
                <= 20 * row["requests"]
                or not 0 <= result["unique_items"] <= row["catalog_items"]
            ):
                raise ValueError("Diversity artifact counts exceed their bounds.")
            previous = 0
            for k in K_VALUES:
                hits = result["hits"][str(k)]
                if not previous <= hits <= result["target_in_pool"] or not math.isclose(
                    result[f"HR@{k}"], hits / row["requests"], rel_tol=0, abs_tol=1e-12
                ):
                    raise ValueError("Diversity artifact hits disagree with rates or rank order.")
                previous = hits


def _validate_completion(artifact: dict, *, phase: str) -> None:
    required = 3 if phase == "development" else 5
    if type(artifact.get("complete")) is not bool or artifact["complete"] != (
        len(artifact["folds"]) == required
    ):
        raise ValueError("Diversity completion flag disagrees with fold count.")


def evaluate_development_fold(
    args: argparse.Namespace, *, index: int, quality: dict, development: dict, manifest: dict
) -> dict:
    expected = quality["folds"][index - 1]
    pairs, training_counts = ranker.training_samples(
        upstream_args(args), quality, list(range(1, index))
    )
    started = perf_counter()
    model = PairwiseRanker.fit(pairs, alpha=0.01, max_iterations=ranker.POLICY["max_iterations"])
    fit_seconds = perf_counter() - started
    catalog = pd.read_parquet(args.fold_dir / f"fold_{index:02d}" / "items_train.parquet")
    categories_by_item = category_map(
        catalog, expected_items=manifest["folds"][index - 1]["train_catalog_items"]
    )
    fold_dir = args.m10_data_dir / f"fold_{index:02d}"
    requests = pd.read_parquet(fold_dir / "requests.parquet")
    if requests["request_id"].duplicated().any() or len(requests) != expected["requests"]:
        raise ValueError("Diversity development request table differs from M10.")
    lookup = requests.set_index("request_id").to_dict("index")
    totals = {str(b): ReRankingTotals(len(categories_by_item)) for b in BONUSES}
    seconds = {key: 0.0 for key in totals}
    seen: set[str] = set()
    for key, frame in iter_candidate_groups(fold_dir / "candidates.parquet"):
        if key not in lookup or key in seen:
            raise ValueError("Diversity candidate request is duplicated or missing.")
        seen.add(key)
        request = lookup[key]
        item_ids = frame["item_id"].astype(str).tolist()
        labels = frame["label"].to_numpy(dtype=np.int8)
        ranks = frame["retrieval_rank"].to_numpy(dtype=np.int64)
        if (
            len(frame) != request["pool_size"]
            or len(set(item_ids)) != len(item_ids)
            or not np.array_equal(ranks, np.arange(1, len(frame) + 1))
            or not np.isin(labels, (0, 1)).all()
            or int(labels.sum()) != request["target_in_pool"]
            or not np.array_equal(
                labels, np.array([item == str(request["target_item_id"]) for item in item_ids])
            )
            or any(item not in categories_by_item for item in item_ids)
        ):
            raise ValueError("Diversity development candidates differ from frozen M10.")
        score_request(
            item_ids=item_ids,
            scores=model.score(feature_matrix(frame)),
            categories=[categories_by_item[item] for item in item_ids],
            target_item=str(request["target_item_id"]),
            target_in_pool=bool(request["target_in_pool"]),
            totals=totals,
            seconds=seconds,
        )
    for key, request in lookup.items():
        if key not in seen:
            if request["pool_size"] != 0 or request["target_in_pool"] != 0:
                raise ValueError("Diversity is missing a nonempty request.")
            score_request(
                item_ids=[],
                scores=np.empty(0),
                categories=[],
                target_item=str(request["target_item_id"]),
                target_in_pool=False,
                totals=totals,
                seconds=seconds,
            )
    outputs = {key: value.output() for key, value in totals.items()}
    check_base_parity(outputs["0.0"], development["folds"][index - 2]["configs"]["0.01"]["metrics"])
    if any(
        value["requests"] != expected["requests"]
        or value["candidate_count"] != expected["candidates"]
        or value["target_in_pool"] != expected["positives"]
        for value in outputs.values()
    ):
        raise ValueError("Diversity development counts differ from M10.")
    return {
        "fold_index": index,
        "cutoff": manifest["folds"][index - 1]["train_cutoff"],
        "catalog_items": len(categories_by_item),
        "requests": expected["requests"],
        "training_folds": list(range(1, index)),
        "training_counts": training_counts,
        "fit_seconds": fit_seconds,
        "rerank_seconds": seconds,
        "configs": outputs,
    }


def select_bonus(rows: list[dict]) -> float:
    if [row["fold_index"] for row in rows] != [2, 3, 4]:
        raise ValueError("Diversity selection requires complete chronological development folds.")
    if any(set(row["configs"]) != {str(b) for b in BONUSES} for row in rows):
        raise ValueError("Diversity development grid is incomplete.")
    requests = sum(row["requests"] for row in rows)
    if requests <= 0:
        raise ValueError("Diversity selection requires nonempty development cohorts.")

    def aggregate(key: str) -> tuple[int, int, float, int]:
        configs = [row["configs"][key] for row in rows]
        return (
            sum(config["distinct_known_category_slots"] for config in configs),
            sum(config["hits"]["20"] for config in configs),
            sum(config["discounted_sum"]["20"] for config in configs),
            sum(config["known_category_item_slots"] for config in configs),
        )

    base_distinct, base_hits, base_ndcg, base_known = aggregate("0.0")
    eligible = []
    for bonus in BONUSES[1:]:
        distinct, hits, ndcg, known = aggregate(str(bonus))
        if (
            distinct > base_distinct
            and (base_hits - hits) / requests <= POLICY["selection"]["hr_max_absolute_loss"]
            and (base_ndcg - ndcg) / requests <= POLICY["selection"]["ndcg_max_absolute_loss"]
            and (base_known - known) / (20 * requests)
            <= POLICY["selection"]["known_category_slots_max_absolute_loss"]
        ):
            eligible.append((distinct, hits, ndcg, -bonus))
    return -max(eligible)[3] if eligible else 0.0


def run_development(args: argparse.Namespace) -> None:
    manifest, _, identity, _, ranker_identity, quality = inputs(args, max_fold=4)
    development = ranker.read_validated_artifact(
        args.ranker_development, {"benchmark": "pairwise-ranker-development-v1", **ranker_identity}
    )
    expected = {"benchmark": "diversity-development-v1", **identity}
    artifact = (
        read_artifact(args.development_artifact, expected)
        if args.development_artifact.exists()
        else {**expected, "folds": [], "complete": False}
    )
    _validate_rows(
        artifact["folds"], manifest, phase="development", names={str(b) for b in BONUSES}
    )
    _validate_completion(artifact, phase="development")
    for index in (2, 3, 4):
        if index < 2 + len(artifact["folds"]):
            continue
        row = evaluate_development_fold(
            args, index=index, quality=quality, development=development, manifest=manifest
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == 3
        if artifact["complete"]:
            artifact["selected_bonus"] = select_bonus(artifact["folds"])
        write_artifact(args.development_artifact, artifact)
        print(f"Saved diversity development fold {index}", flush=True)
    if artifact["complete"] and artifact.get("selected_bonus") != select_bonus(artifact["folds"]):
        raise ValueError("Diversity saved selection differs from the frozen rule.")


def require_development_and_lock(
    args: argparse.Namespace, identity: dict, manifest: dict
) -> tuple[dict, dict]:
    expected = {"benchmark": "diversity-development-v1", **identity}
    development = read_artifact(args.development_artifact, expected)
    _validate_rows(
        development["folds"], manifest, phase="development", names={str(b) for b in BONUSES}
    )
    _validate_completion(development, phase="development")
    if not development["complete"]:
        raise ValueError("Diversity diagnostic requires complete development folds 2–4.")
    selected = select_bonus(development["folds"])
    if development.get("selected_bonus") != selected:
        raise ValueError("Diversity development selection differs from the frozen rule.")
    lock_expected = {
        "benchmark": "diversity-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "selected_bonus": selected,
    }
    return development, read_artifact(args.selection_lock, lock_expected)


def run_lock(args: argparse.Namespace) -> None:
    manifest, _, identity, _, _, _ = inputs(args, max_fold=4)
    development = read_artifact(
        args.development_artifact, {"benchmark": "diversity-development-v1", **identity}
    )
    _validate_rows(
        development["folds"], manifest, phase="development", names={str(b) for b in BONUSES}
    )
    _validate_completion(development, phase="development")
    if not development["complete"]:
        raise ValueError("Diversity selection requires complete development folds.")
    selected = select_bonus(development["folds"])
    if development.get("selected_bonus") != selected:
        raise ValueError("Diversity development selection differs from the frozen rule.")
    lock = {
        "benchmark": "diversity-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "selected_bonus": selected,
        "role": "locked development choice; later folds are post-selection diagnostics",
    }
    if args.selection_lock.exists():
        read_artifact(args.selection_lock, lock)
    else:
        write_artifact(args.selection_lock, lock)
    print(f"Locked category bonus={selected}", flush=True)


def locked_ranker_model(
    args: argparse.Namespace, ranker_identity: dict
) -> tuple[PairwiseRanker, dict]:
    expected = {
        "benchmark": "pairwise-ranker-diagnostic-v1",
        **ranker_identity,
        "selection_lock_sha256": sha256_file(args.ranker_lock),
        "selected_alpha": 0.01,
    }
    diagnostic = ranker.read_validated_artifact(args.ranker_diagnostic, expected)
    if not diagnostic.get("complete") or [row["fold_index"] for row in diagnostic["folds"]] != list(
        range(5, 10)
    ):
        raise ValueError("Diversity requires all five frozen ranker diagnostic folds.")
    record = diagnostic["model"]
    if diagnostic["model_sha256"] != ranker.digest_json(record) or record["alpha"] != 0.01:
        raise ValueError("Diversity model record differs from the frozen diagnostic.")
    weights = np.asarray(record["weights"], dtype=np.float64)
    scales = np.asarray(record["scales"], dtype=np.float64)
    if (
        weights.shape != (len(ranker.FEATURE_NAMES),)
        or scales.shape != weights.shape
        or not np.isfinite(weights).all()
        or not np.isfinite(scales).all()
        or not (scales > 0).all()
    ):
        raise ValueError("Diversity model weights or scales are invalid.")
    return PairwiseRanker(
        weights, scales, 0.01, record["iterations"], record["converged"]
    ), diagnostic


def evaluate_live_fold(
    *,
    index: int,
    fold: dict,
    interactions: pd.DataFrame,
    fold_dir: Path,
    configs: dict,
    model: PairwiseRanker,
    reference_row: dict,
    ranker_row: dict,
    selected_bonus: float,
) -> dict:
    cutoff = int(fold["train_cutoff"])
    train = interactions.loc[interactions["timestamp"] <= cutoff]
    catalog = pd.read_parquet(fold_dir / "items_train.parquet")
    targets = pd.read_parquet(fold_dir / "warm_targets.parquet")
    if len(train) != fold["training_interactions"] or len(targets) != fold["warm_target_users"]:
        raise ValueError("Diversity diagnostic fold counts differ from rolling manifest.")
    if (train["timestamp"] > cutoff).any() or not (
        (targets["timestamp"] > cutoff) & (targets["timestamp"] <= int(fold["evaluation_cutoff"]))
    ).all():
        raise ValueError("Diversity diagnostic timestamps cross the declared boundary.")
    validate_targets(train, targets, "warm")
    categories_by_item = category_map(catalog, expected_items=fold["train_catalog_items"])
    catalog_ids = frozenset(categories_by_item)
    if set(train["item_id"].astype(str)) != catalog_ids:
        raise ValueError("Diversity diagnostic catalog differs from train interactions.")
    started = perf_counter()
    _, hybrids, _, _ = ranker.build_sources(train, catalog, cutoff, configs)
    fit_seconds = perf_counter() - started
    hybrid = next((generator for generator in hybrids if generator.name == "hybrid"), None)
    if hybrid is None:
        raise ValueError("Diversity diagnostic requires the frozen full hybrid.")
    features = SnapshotFeatures.from_frames(train, catalog, cutoff)
    ids = set(targets["user_id"].astype(str))
    history_rows = train.loc[train["user_id"].astype(str).isin(ids)].copy()
    history_rows["user_id"] = history_rows["user_id"].astype(str)
    histories = {
        user: tuple(group["item_id"].astype(str))
        for user, group in history_rows.groupby("user_id", sort=False)
    }
    names = diagnostic_keys(selected_bonus)
    totals = {key: ReRankingTotals(len(catalog_ids)) for key in names}
    rerank_seconds = {key: 0.0 for key in names}
    empty = 0
    retrieval_seconds = feature_seconds = scoring_seconds = 0.0
    for position, target in enumerate(targets.itertuples(index=False), start=1):
        user = str(target.user_id)
        target_item = str(target.item_id)
        context = RetrievalContext(user, histories[user])
        seen = frozenset(context.history)
        started = perf_counter()
        pool = hybrid.generate(context, CANDIDATE_BUDGET)
        retrieval_seconds += perf_counter() - started
        if any(
            candidate.item_id in seen or candidate.item_id not in catalog_ids for candidate in pool
        ):
            raise ValueError("Diversity diagnostic pool contains seen or unknown items.")
        started = perf_counter()
        request = request_row(
            fold_index=index,
            cutoff=cutoff,
            evaluation_cutoff=int(fold["evaluation_cutoff"]),
            user_id=user,
            target_item_id=target_item,
            target_timestamp=int(target.timestamp),
            catalog=catalog_ids,
            candidates=pool,
            request_key=request_id(index, user),
        )
        rows = [
            features.candidate_row(
                fold_index=index,
                context=context,
                candidate=candidate,
                rank=rank,
                target_item_id=target_item,
                request_key=request["request_id"],
                seen_items=seen,
            )
            for rank, candidate in enumerate(pool, start=1)
        ]
        feature_seconds += perf_counter() - started
        item_ids = [row["item_id"] for row in rows]
        if sum(row["label"] for row in rows) != request["target_in_pool"]:
            raise ValueError("Diversity diagnostic label differs from target availability.")
        started = perf_counter()
        scores = model.score(feature_matrix(pd.DataFrame(rows))) if rows else np.empty(0)
        scoring_seconds += perf_counter() - started
        if not rows:
            empty += 1
        score_request(
            item_ids=item_ids,
            scores=scores,
            categories=[categories_by_item[item] for item in item_ids],
            target_item=target_item,
            target_in_pool=bool(request["target_in_pool"]),
            totals=totals,
            seconds=rerank_seconds,
        )
        if position % 500 == 0 or position == len(targets):
            print(f"  diversity diagnostic fold {index}: {position:,}/{len(targets):,}", flush=True)
    outputs = {key: accumulator.output() for key, accumulator in totals.items()}
    check_base_parity(outputs["0.0"], ranker_row["metrics"])
    reference_totals = reference_row["totals"]["1000"]
    if (
        any(
            result["requests"] != fold["warm_target_users"]
            or result["target_in_pool"] != reference_totals["hits"]
            or result["candidate_count"] != reference_totals["candidate_count"]
            for result in outputs.values()
        )
        or empty != reference_totals["empty_requests"]
    ):
        raise ValueError("Diversity diagnostic pool differs from frozen M7 reference.")
    return {
        "fold_index": index,
        "cutoff": cutoff,
        "catalog_items": len(catalog_ids),
        "requests": len(targets),
        "configs": outputs,
        "empty_requests": empty,
        "fit_seconds": fit_seconds,
        "retrieval_seconds": retrieval_seconds,
        "feature_seconds": feature_seconds,
        "scoring_seconds": scoring_seconds,
        "rerank_seconds": rerank_seconds,
    }


def run_diagnostic(args: argparse.Namespace) -> None:
    if not 5 <= args.max_fold <= 9:
        raise ValueError("Diversity diagnostic max fold must be in 5–9.")
    manifest, configs, identity, reference_rows, ranker_identity, _ = inputs(
        args, max_fold=args.max_fold
    )
    _, lock = require_development_and_lock(args, identity, manifest)
    model, ranker_diagnostic = locked_ranker_model(args, ranker_identity)
    selected = lock["selected_bonus"]
    expected = {
        "benchmark": "diversity-diagnostic-v1",
        **identity,
        "selection_lock_sha256": sha256_file(args.selection_lock),
        "ranker_diagnostic_sha256": sha256_file(args.ranker_diagnostic),
        "selected_bonus": selected,
    }
    artifact = (
        read_artifact(args.diagnostic_artifact, expected)
        if args.diagnostic_artifact.exists()
        else {
            **expected,
            "role": "post-selection diagnostic; not blind validation",
            "folds": [],
            "complete": False,
        }
    )
    names = diagnostic_keys(selected)
    _validate_rows(artifact["folds"], manifest, phase="diagnostic", names=set(names))
    _validate_completion(artifact, phase="diagnostic")
    interactions = pd.read_parquet(args.input_path)
    for fold in manifest["folds"][4 : args.max_fold]:
        index = fold["fold_index"]
        if index < 5 + len(artifact["folds"]):
            continue
        row = evaluate_live_fold(
            index=index,
            fold=fold,
            interactions=interactions,
            fold_dir=args.fold_dir / f"fold_{index:02d}",
            configs=configs,
            model=model,
            reference_row=reference_rows[index],
            ranker_row=ranker_diagnostic["folds"][index - 5],
            selected_bonus=selected,
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == 5
        write_artifact(args.diagnostic_artifact, artifact)
        print(f"Saved diversity diagnostic fold {index}", flush=True)


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("development", "lock", "diagnostic"))
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--sweep-dir", type=Path, default=Path("benchmarks/rolling"))
    parser.add_argument(
        "--reference", type=Path, default=Path("benchmarks/retrieval/candidates.json")
    )
    parser.add_argument("--m10-data-dir", type=Path, default=Path("data/ranking/m10_v1"))
    parser.add_argument(
        "--m10-quality", type=Path, default=Path("benchmarks/ranking/m10_quality_v1.json")
    )
    parser.add_argument(
        "--ranker-development",
        type=Path,
        default=Path("benchmarks/ranking/ranker_development_v1.json"),
    )
    parser.add_argument(
        "--ranker-lock", type=Path, default=Path("benchmarks/ranking/ranker_selection_lock_v1.json")
    )
    parser.add_argument(
        "--ranker-diagnostic",
        type=Path,
        default=Path("benchmarks/ranking/ranker_diagnostic_v1.json"),
    )
    parser.add_argument(
        "--development-artifact",
        type=Path,
        default=Path("benchmarks/ranking/diversity_development_v1.json"),
    )
    parser.add_argument(
        "--selection-lock",
        type=Path,
        default=Path("benchmarks/ranking/diversity_selection_lock_v1.json"),
    )
    parser.add_argument(
        "--diagnostic-artifact",
        type=Path,
        default=Path("benchmarks/ranking/diversity_diagnostic_v1.json"),
    )
    parser.add_argument("--max-fold", type=int, default=9)
    args = parser.parse_args()
    if args.phase == "development":
        run_development(args)
    elif args.phase == "lock":
        run_lock(args)
    else:
        run_diagnostic(args)


if __name__ == "__main__":
    main()
