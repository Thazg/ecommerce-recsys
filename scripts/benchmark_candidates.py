"""Measure M7 source and hybrid recall on the existing causal rolling cohorts."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import scipy

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.candidates import (
    N_VALUES,
    evaluate_candidate_sources,
    summarize_candidates,
)
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.retrieval.category_retriever import CategoryRetriever
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator
from ecommerce_recsys.retrieval.item_knn_retriever import ItemKNNRetriever
from ecommerce_recsys.retrieval.mf_retriever import MFRetriever
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever

GENERATORS = (
    "item_knn",
    "als",
    "category_popularity",
    "recent_popularity",
    "global_popularity",
    "hybrid",
    "hybrid_without_als",
)
POLICY = {
    "n_values": list(N_VALUES),
    "source_pool_size": 1000,
    "fusion": "equal-weight reciprocal rank fusion",
    "rank_constant": 60.0,
    "recent_window_days": 30,
    "category_policy": "training count across history categories, no fallback",
    "cold_latency_samples": 100,
    "numeric_threads": 1,
    "source_rank_policy": "eligible source-list rank; fusion preserves supplied ranks",
    "fallback_policy": "explicit popularity sources; personalized sources may be empty",
    "latency_quantile_method": "linear",
}


def implementation_paths(root: Path) -> list[Path]:
    # Include the complete package so changes to catalog, cutoff, fallback,
    # scoring, evaluation, or numerical-thread behavior invalidate checkpoints.
    return [
        *sorted((root / "src/ecommerce_recsys").rglob("*.py")),
        root / "scripts/prepare_rolling_data.py",
        root / "scripts/benchmark_candidates.py",
        root / "pyproject.toml",
    ]


def implementation_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in implementation_paths(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def payload_fingerprint(artifact: dict) -> str:
    payload = {
        key: artifact.get(key)
        for key in ("results", "fold_costs", "development_summary", "post_selection_summary")
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def save_checkpoint(path: Path, artifact: dict) -> None:
    artifact["payload_sha256"] = payload_fingerprint(artifact)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def validate_checkpoint(artifact: dict, expected: dict, manifest: dict) -> None:
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise ValueError("Checkpoint provenance, implementation or retrieval policy changed.")
    if artifact.get("payload_sha256") != payload_fingerprint(artifact):
        raise ValueError("Checkpoint result content does not match its fingerprint.")
    keys = set()
    folds = {fold["fold_index"]: fold for fold in manifest["folds"]}
    for row in artifact.get("results", []):
        key = (row.get("fold_index"), row.get("cohort"), row.get("generator"))
        if (
            key in keys
            or key[0] not in folds
            or key[1] not in expected["cohorts"]
            or key[2] not in GENERATORS
        ):
            raise ValueError("Checkpoint has invalid or duplicate result rows.")
        if row["evaluation_users"] != folds[key[0]][f"{key[1]}_target_users"]:
            raise ValueError("Checkpoint cohort size does not match the rolling manifest.")
        if not 0 <= row["reachable_targets"] <= row["evaluation_users"]:
            raise ValueError("Checkpoint contains invalid reachable-target counts.")
        for n in N_VALUES:
            totals = row["totals"][str(n)]
            if not (
                0 <= totals["hits"] <= row["reachable_targets"]
                and 0 <= totals["candidate_count"] <= n * row["evaluation_users"]
                and 0
                <= totals["empty_requests"] + totals["full_requests"]
                <= row["evaluation_users"]
                and 0 <= totals["unique_items"] <= folds[key[0]]["train_catalog_items"]
            ):
                raise ValueError("Checkpoint candidate totals are outside valid bounds.")
        keys.add(key)
    for index in folds:
        for cohort in expected["cohorts"]:
            present = {name for fold, kind, name in keys if fold == index and kind == cohort}
            if present and present != set(GENERATORS):
                raise ValueError("Checkpoint contains a partial source comparison.")


def build_sources(train: pd.DataFrame, catalog: pd.DataFrame, cutoff: int, configs: dict):
    ids = catalog["item_id"].astype(str)
    sources, fit_seconds = [], {}
    started = perf_counter()
    knn = ItemKNNRecommender(n_neighbors=20, min_item_interactions=5, **configs["item_knn"])
    knn.fit(train)
    sources.append(ItemKNNRetriever(knn, ids))
    fit_seconds["item_knn"] = perf_counter() - started
    started = perf_counter()
    als = MatrixFactorizationRecommender(**configs["als"], random_state=42)
    als.fit(train)
    sources.append(MFRetriever(als, ids))
    fit_seconds["als"] = perf_counter() - started
    factor_memory_bytes = als.factor_memory_bytes
    for name, constructor in (
        ("category_popularity", lambda: CategoryRetriever(train, catalog)),
        (
            "recent_popularity",
            lambda: PopularityRetriever(train, ids, window_days=30, cutoff=cutoff),
        ),
        ("global_popularity", lambda: PopularityRetriever(train, ids)),
    ):
        started = perf_counter()
        sources.append(constructor())
        fit_seconds[name] = perf_counter() - started
    hybrids = [
        HybridCandidateGenerator(sources),
        HybridCandidateGenerator(
            [s for s in sources if s.name != "als"], name="hybrid_without_als"
        ),
    ]
    return sources, hybrids, fit_seconds, factor_memory_bytes


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--sweep-dir", type=Path, default=Path("benchmarks/rolling"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/retrieval/candidates.json"))
    parser.add_argument("--max-fold", type=int, default=9)
    parser.add_argument("--cohorts", nargs="+", choices=("warm", "cold"), default=["warm", "cold"])
    args = parser.parse_args()
    if not 1 <= args.max_fold <= 9:
        raise ValueError("max-fold must be between 1 and 9.")
    if len(set(args.cohorts)) != len(args.cohorts):
        raise ValueError("Cohorts must be unique.")
    import implicit

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_version") != "rolling-temporal":
        raise ValueError("Expected rolling temporal manifest.")
    fingerprint = manifest_fingerprint(manifest)
    require_completed_sweeps(args.sweep_dir, manifest)
    configs = {
        name: json.loads((args.sweep_dir / f"{name}_sweep.json").read_text(encoding="utf-8"))[
            "selected_config"
        ]
        for name in ("item_knn", "als")
    }
    expected = {
        "benchmark": "rolling-candidate-retrieval",
        "protocol_version": manifest["protocol_version"],
        "source_sha256": manifest["source_sha256"],
        "manifest_sha256": fingerprint,
        "implementation_sha256": implementation_fingerprint(),
        "model_configs": configs,
        "sweep_sha256": {
            name: sha256_file(args.sweep_dir / f"{name}_sweep.json") for name in configs
        },
        "policy": POLICY,
        "cohorts": sorted(args.cohorts),
        "blind_holdout": False,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "implicit": implicit.__version__,
        },
    }
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Input interactions do not match the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir, args.max_fold)
    if args.output.exists():
        artifact = json.loads(args.output.read_text(encoding="utf-8"))
        validate_checkpoint(artifact, expected, manifest)
    else:
        artifact = {
            **expected,
            "role": "post-selection candidate diagnostics; no blind holdout",
            "unit": "user-window",
            "latency_excludes": ["fit", "data loading", "final ranker", "API"],
            "results": [],
            "fold_costs": [],
        }
    done = {(row["fold_index"], row["cohort"]) for row in artifact["results"]}
    interactions = pd.read_parquet(args.input_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for fold in manifest["folds"][: args.max_fold]:
        index = fold["fold_index"]
        missing = [cohort for cohort in args.cohorts if (index, cohort) not in done]
        if not missing:
            continue
        print(f"Fold {index}: fitting selected candidate sources", flush=True)
        train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]]
        path = args.fold_dir / f"fold_{index:02d}"
        catalog = pd.read_parquet(path / "items_train.parquet")
        if (
            len(train) != fold["training_interactions"]
            or len(catalog) != fold["train_catalog_items"]
        ):
            raise ValueError("Training snapshot or catalog count differs from manifest.")
        if catalog["item_id"].astype(str).duplicated().any():
            raise ValueError("Catalog contains duplicate item IDs.")
        if set(train["item_id"].astype(str)) != set(catalog["item_id"].astype(str)):
            raise ValueError("Catalog differs from the train-only item set.")
        sources, hybrids, fit_seconds, factor_memory_bytes = build_sources(
            train, catalog, fold["train_cutoff"], configs
        )
        fold_started = perf_counter()
        for cohort in missing:
            print(f"  {cohort}: evaluating candidates", flush=True)
            targets = pd.read_parquet(path / f"{cohort}_targets.parquet")
            if len(targets) != fold[f"{cohort}_target_users"]:
                raise ValueError("Target count differs from manifest.")
            if (
                not targets.empty
                and not targets["timestamp"]
                .between(fold["train_cutoff"] + 1, fold["evaluation_cutoff"])
                .all()
            ):
                raise ValueError("Targets fall outside the declared future window.")
            rows = evaluate_candidate_sources(train, targets, sources, hybrids, cohort=cohort)
            artifact["results"].extend({"fold_index": index, **row} for row in rows)
        artifact["fold_costs"].append(
            {
                "fold_index": index,
                "fit_seconds": fit_seconds,
                "als_factor_memory_bytes": factor_memory_bytes,
                "evaluation_seconds": perf_counter() - fold_started,
            }
        )
        artifact["development_summary"] = summarize_candidates(
            [row for row in artifact["results"] if row["fold_index"] <= 4]
        )
        artifact["post_selection_summary"] = summarize_candidates(
            [row for row in artifact["results"] if row["fold_index"] >= 5]
        )
        save_checkpoint(args.output, artifact)
        print(f"  Saved fold {index} to {args.output}", flush=True)
        # Release previous-fold factor arrays before fitting the next snapshot.
        del sources, hybrids, train, catalog
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
