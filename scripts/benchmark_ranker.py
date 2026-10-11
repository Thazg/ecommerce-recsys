"""Select and evaluate a same-pool offline pairwise ranker on rolling folds."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import pyarrow as pa
import scipy

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.candidates import validate_targets
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from ecommerce_recsys.ranking.dataset import (
    CANDIDATE_BUDGET,
    SnapshotFeatures,
    request_id,
    request_row,
)
from ecommerce_recsys.retrieval.base import RetrievalContext

if __package__:
    from scripts.benchmark_candidates import POLICY as M7_POLICY
    from scripts.benchmark_candidates import build_sources
    from scripts.build_ranking_dataset import POLICY as M10_POLICY
    from scripts.build_ranking_dataset import (
        REQUEST_SCHEMA,
        candidate_schema,
    )
    from scripts.build_ranking_dataset import (
        implementation_fingerprint as m10_implementation_fingerprint,
    )
    from scripts.build_ranking_dataset import (
        validate_checkpoint as validate_m10_checkpoint,
    )
    from scripts.learned_ranker import (
        FEATURE_NAMES,
        PairwiseRanker,
        RankingTotals,
        feature_matrix,
        iter_candidate_groups,
        positive_rank,
        sample_training_pairs,
    )
else:
    from benchmark_candidates import POLICY as M7_POLICY
    from benchmark_candidates import build_sources
    from build_ranking_dataset import POLICY as M10_POLICY
    from build_ranking_dataset import (
        REQUEST_SCHEMA,
        candidate_schema,
    )
    from build_ranking_dataset import (
        implementation_fingerprint as m10_implementation_fingerprint,
    )
    from build_ranking_dataset import (
        validate_checkpoint as validate_m10_checkpoint,
    )
    from learned_ranker import (
        FEATURE_NAMES,
        PairwiseRanker,
        RankingTotals,
        feature_matrix,
        iter_candidate_groups,
        positive_rank,
        sample_training_pairs,
    )

POLICY = {
    "version": 1,
    "cohort": "warm",
    "candidate_generator": "fixed full M7 hybrid",
    "candidate_budget": CANDIDATE_BUDGET,
    "development_train_evaluate": [[1, 2], [2, 3], [3, 4]],
    "development_evaluation_folds": [2, 3, 4],
    "diagnostic_folds": [5, 6, 7, 8, 9],
    "model": "linear pairwise logistic with L2",
    "feature_transforms": {
        "counts_and_nonnegative_recency": "log1p",
        "ranks": "1/(60+rank)",
        "source_scores": "signed log1p(abs(score))",
        "other": "identity",
        "scale": "RMS of training pair differences only",
    },
    "negative_sampling": {
        "top_rrf_negatives": 20,
        "uniform_remaining_negatives": 80,
        "seed": 42,
        "skip_zero_positive_training_requests": True,
    },
    "alpha_grid": [0.0001, 0.001, 0.01],
    "max_iterations": 100,
    "selection_rule": "pooled HR@20, then pooled NDCG@20, then larger alpha",
    "tie_break": "descending learned score, ascending item ID",
    "numeric_threads": 1,
    "blind_holdout": False,
}


def code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "scripts/benchmark_ranker.py",
        root / "scripts/learned_ranker.py",
        root / "scripts/build_ranking_dataset.py",
        root / "scripts/benchmark_candidates.py",
        root / "pyproject.toml",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    digest.update(m10_implementation_fingerprint().encode())
    return digest.hexdigest()


def digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def write_json_atomic(path: Path, artifact: dict) -> None:
    artifact["payload_sha256"] = digest_json(
        {key: value for key, value in artifact.items() if key != "payload_sha256"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def read_validated_artifact(path: Path, expected: dict) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{path.name} provenance or policy differs from current inputs.")
    claimed = artifact.get("payload_sha256")
    actual = digest_json({key: value for key, value in artifact.items() if key != "payload_sha256"})
    if claimed != actual:
        raise ValueError(f"{path.name} payload checksum differs from its contents.")
    return artifact


def input_identity(args: argparse.Namespace) -> tuple[dict, dict, dict, dict[int, dict]]:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_version") != "rolling-temporal":
        raise ValueError("Ranker requires the rolling-temporal manifest.")
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Ranker interactions do not match the rolling manifest.")
    require_completed_sweeps(args.sweep_dir, manifest)
    configs = {
        name: json.loads((args.sweep_dir / f"{name}_sweep.json").read_text(encoding="utf-8"))[
            "selected_config"
        ]
        for name in ("item_knn", "als")
    }
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    if (
        reference.get("manifest_sha256") != manifest_fingerprint(manifest)
        or reference.get("model_configs") != configs
        or reference.get("policy") != M7_POLICY
    ):
        raise ValueError("Ranker M7 reference differs from the selected rolling policy.")
    reference_rows = {
        row["fold_index"]: row
        for row in reference["results"]
        if row["cohort"] == "warm" and row["generator"] == "hybrid"
    }
    if set(reference_rows) != set(range(1, 10)):
        raise ValueError("Ranker requires all nine M7 warm hybrid reference rows.")
    identity = {
        "protocol_version": "rolling-temporal",
        "manifest_sha256": manifest_fingerprint(manifest),
        "source_sha256": manifest["source_sha256"],
        "raw_property_sha256": manifest["raw_property_sha256"],
        "m7_reference_sha256": sha256_file(args.reference),
        "sweep_sha256": {
            name: sha256_file(args.sweep_dir / f"{name}_sweep.json") for name in configs
        },
        "model_configs": configs,
        "m7_policy": M7_POLICY,
        "m10_policy": M10_POLICY,
        "policy": POLICY,
        "feature_names": list(FEATURE_NAMES),
        "feature_schema": str(candidate_schema()),
        "code_sha256": code_fingerprint(),
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pa.__version__,
            "scipy": scipy.__version__,
        },
    }
    return manifest, configs, identity, reference_rows


def validate_development_data(args: argparse.Namespace, identity: dict) -> dict:
    quality = json.loads(args.m10_quality.read_text(encoding="utf-8"))
    expected = {
        "manifest_sha256": identity["manifest_sha256"],
        "source_sha256": identity["source_sha256"],
        "raw_property_sha256": identity["raw_property_sha256"],
        "m7_reference_sha256": identity["m7_reference_sha256"],
        "sweep_sha256": identity["sweep_sha256"],
        "model_configs": identity["model_configs"],
        "m7_policy": M7_POLICY,
        "policy": M10_POLICY,
        "feature_schema": str(candidate_schema()),
        "request_schema": str(REQUEST_SCHEMA),
        "implementation_sha256": m10_implementation_fingerprint(),
    }
    validate_m10_checkpoint(quality, expected, args.m10_data_dir)
    if [row["fold_index"] for row in quality["folds"]] != [1, 2, 3, 4]:
        raise ValueError("Ranker requires a complete M10 development dataset.")
    identity["m10_quality_sha256"] = sha256_file(args.m10_quality)
    identity["m10_data_sha256"] = quality["data_sha256"]
    return quality


def evaluate_parquet_fold(path: Path, model: PairwiseRanker, expected: dict) -> dict:
    fold_dir = path / f"fold_{expected['fold_index']:02d}"
    requests = pd.read_parquet(fold_dir / "requests.parquet")
    if requests["request_id"].duplicated().any() or len(requests) != expected["requests"]:
        raise ValueError("Ranker request table contains duplicate or missing requests.")
    lookup = requests.set_index("request_id").to_dict("index")
    totals = RankingTotals()
    seen: set[str] = set()
    for key, frame in iter_candidate_groups(fold_dir / "candidates.parquet"):
        if key not in lookup or key in seen:
            raise ValueError("Ranker candidate request is duplicated or absent from requests.")
        seen.add(key)
        request = lookup[key]
        ranks = frame["retrieval_rank"].to_numpy(dtype=np.int64)
        labels = frame["label"].to_numpy(dtype=np.int8)
        items = frame["item_id"].to_numpy(dtype=str)
        if (
            len(frame) != request["pool_size"]
            or not np.array_equal(ranks, np.arange(1, len(frame) + 1))
            or not np.isin(labels, (0, 1)).all()
            or int(labels.sum()) != request["target_in_pool"]
            or not np.array_equal(labels, (items == str(request["target_item_id"])).astype(int))
        ):
            raise ValueError("Ranker candidates do not reconcile with M10 request labels/ranks.")
        learned = positive_rank(model.score(feature_matrix(frame)), items, labels)
        baseline = int(np.flatnonzero(labels == 1)[0] + 1) if labels.sum() else None
        totals.add(pool_size=len(frame), rrf_rank=baseline, learned_rank=learned)
    for key, request in lookup.items():
        if key not in seen:
            if request["pool_size"] != 0 or request["target_in_pool"] != 0:
                raise ValueError("Ranker is missing a nonempty candidate request.")
            totals.add(pool_size=0, rrf_rank=None, learned_rank=None)
    if (
        totals.requests != expected["requests"]
        or totals.candidates != expected["candidates"]
        or totals.in_pool != expected["positives"]
    ):
        raise ValueError("Ranker metrics do not reconcile with frozen M10 fold counts.")
    return totals.as_dict()


def training_samples(
    args: argparse.Namespace, quality: dict, folds: list[int]
) -> tuple[np.ndarray, dict]:
    pieces: list[np.ndarray] = []
    counts = {"requests": 0, "positive_requests": 0, "zero_positive_requests": 0, "pairs": 0}
    for index in folds:
        row = quality["folds"][index - 1]
        sampled = sample_training_pairs(
            args.m10_data_dir / f"fold_{index:02d}" / "candidates.parquet",
            seed=POLICY["negative_sampling"]["seed"],
        )
        if sampled.requests != row["requests"] or sampled.positive_requests != row["positives"]:
            raise ValueError("Training pair counts differ from M10 request/positive counts.")
        pieces.append(sampled.differences)
        for key in counts:
            counts[key] += getattr(sampled, key)
    return np.concatenate(pieces), counts


def select_alpha(rows: list[dict]) -> float:
    if [row["fold_index"] for row in rows] != [2, 3, 4]:
        raise ValueError("Ranker selection requires complete development folds 2–4.")
    if any(set(row["configs"]) != {str(alpha) for alpha in POLICY["alpha_grid"]} for row in rows):
        raise ValueError("Ranker selection grid is incomplete.")
    ranking: list[tuple[int, float, float]] = []
    for alpha in POLICY["alpha_grid"]:
        key = str(alpha)
        hits = sum(row["configs"][key]["metrics"]["learned"]["hits"]["20"] for row in rows)
        ndcg = sum(
            row["configs"][key]["metrics"]["learned"]["NDCG@20"] * row["requests"] for row in rows
        )
        ranking.append((hits, ndcg, alpha))
    return max(ranking)[2]


def run_development(args: argparse.Namespace) -> None:
    manifest, _, identity, _ = input_identity(args)
    verify_fold_files(manifest, args.fold_dir, 4)
    quality = validate_development_data(args, identity)
    expected = {"benchmark": "pairwise-ranker-development-v1", **identity}
    if args.development_artifact.exists():
        artifact = read_validated_artifact(args.development_artifact, expected)
        indices = [row["fold_index"] for row in artifact.get("folds", [])]
        if indices != list(range(2, 2 + len(indices))) or len(indices) > 3:
            raise ValueError("Ranker development artifact has invalid fold order.")
    else:
        artifact = {**expected, "folds": [], "complete": False}
    for evaluation_fold in (2, 3, 4):
        if evaluation_fold < 2 + len(artifact["folds"]):
            continue
        pairs, training_counts = training_samples(args, quality, list(range(1, evaluation_fold)))
        configs: dict = {}
        for alpha in POLICY["alpha_grid"]:
            started = perf_counter()
            model = PairwiseRanker.fit(pairs, alpha=alpha, max_iterations=POLICY["max_iterations"])
            fit_seconds = perf_counter() - started
            metrics = evaluate_parquet_fold(
                args.m10_data_dir, model, quality["folds"][evaluation_fold - 1]
            )
            configs[str(alpha)] = {
                "metrics": metrics,
                "fit_seconds": fit_seconds,
                "optimizer_iterations": model.iterations,
                "converged": model.converged,
            }
            print(
                f"Development fold {evaluation_fold}, alpha={alpha}: "
                f"HR@20={metrics['learned']['HR@20']:.6f}",
                flush=True,
            )
        artifact["folds"].append(
            {
                "fold_index": evaluation_fold,
                "training_folds": list(range(1, evaluation_fold)),
                "training_counts": training_counts,
                "requests": quality["folds"][evaluation_fold - 1]["requests"],
                "configs": configs,
            }
        )
        artifact["complete"] = len(artifact["folds"]) == 3
        if artifact["complete"]:
            artifact["selected_alpha"] = select_alpha(artifact["folds"])
        write_json_atomic(args.development_artifact, artifact)
    print(f"Saved {args.development_artifact}", flush=True)


def require_development_and_lock(args: argparse.Namespace, identity: dict) -> tuple[dict, dict]:
    expected = {"benchmark": "pairwise-ranker-development-v1", **identity}
    development = read_validated_artifact(args.development_artifact, expected)
    if not development.get("complete") or len(development.get("folds", [])) != 3:
        raise ValueError("Ranker development artifact must be complete before diagnostic access.")
    selected = select_alpha(development["folds"])
    if development.get("selected_alpha") != selected:
        raise ValueError("Ranker development selection differs from the locked rule.")
    lock_expected = {
        "benchmark": "pairwise-ranker-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "selected_alpha": selected,
    }
    lock = read_validated_artifact(args.selection_lock, lock_expected)
    return development, lock


def run_lock(args: argparse.Namespace) -> None:
    manifest, _, identity, _ = input_identity(args)
    verify_fold_files(manifest, args.fold_dir, 4)
    validate_development_data(args, identity)
    expected = {"benchmark": "pairwise-ranker-development-v1", **identity}
    development = read_validated_artifact(args.development_artifact, expected)
    if not development.get("complete") or len(development.get("folds", [])) != 3:
        raise ValueError("Ranker selection requires complete development folds 2–4.")
    alpha = select_alpha(development["folds"])
    if development.get("selected_alpha") != alpha:
        raise ValueError("Ranker development artifact selected alpha differs from rule.")
    lock = {
        "benchmark": "pairwise-ranker-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "selected_alpha": alpha,
        "role": "locked development choice; later folds are post-selection diagnostics",
    }
    if args.selection_lock.exists():
        read_validated_artifact(args.selection_lock, lock)
    else:
        write_json_atomic(args.selection_lock, lock)
    print(f"Locked alpha={alpha} in {args.selection_lock}", flush=True)


def evaluate_live_fold(
    *,
    index: int,
    fold: dict,
    interactions: pd.DataFrame,
    fold_dir: Path,
    configs: dict,
    model: PairwiseRanker,
    reference_row: dict,
) -> dict:
    cutoff = int(fold["train_cutoff"])
    train = interactions.loc[interactions["timestamp"] <= cutoff]
    catalog = pd.read_parquet(fold_dir / "items_train.parquet")
    targets = pd.read_parquet(fold_dir / "warm_targets.parquet")
    if len(train) != fold["training_interactions"] or len(targets) != fold["warm_target_users"]:
        raise ValueError("Diagnostic fold counts differ from rolling manifest.")
    if (train["timestamp"] > cutoff).any() or not (
        (targets["timestamp"] > cutoff) & (targets["timestamp"] <= int(fold["evaluation_cutoff"]))
    ).all():
        raise ValueError("Diagnostic fold timestamps cross the declared boundary.")
    validate_targets(train, targets, "warm")
    catalog_ids = frozenset(catalog["item_id"].astype(str))
    if (
        len(catalog_ids) != fold["train_catalog_items"]
        or set(train["item_id"].astype(str)) != catalog_ids
    ):
        raise ValueError("Diagnostic catalog differs from training interactions.")
    started_fit = perf_counter()
    _, hybrids, _, _ = build_sources(train, catalog, cutoff, configs)
    fit_seconds = perf_counter() - started_fit
    hybrid = next((generator for generator in hybrids if generator.name == "hybrid"), None)
    if hybrid is None:
        raise ValueError("Diagnostic requires the fixed full hybrid.")
    features = SnapshotFeatures.from_frames(train, catalog, cutoff)
    ids = set(targets["user_id"].astype(str))
    history_rows = train.loc[train["user_id"].astype(str).isin(ids)].copy()
    history_rows["user_id"] = history_rows["user_id"].astype(str)
    histories = {
        user: tuple(group["item_id"].astype(str))
        for user, group in history_rows.groupby("user_id", sort=False)
    }
    totals = RankingTotals()
    empty = 0
    retrieval_seconds = 0.0
    feature_seconds = 0.0
    scoring_seconds = 0.0
    for position, target in enumerate(targets.itertuples(index=False), start=1):
        user = str(target.user_id)
        target_item = str(target.item_id)
        context = RetrievalContext(user, histories[user])
        seen = frozenset(context.history)
        began = perf_counter()
        pool = hybrid.generate(context, CANDIDATE_BUDGET)
        retrieval_seconds += perf_counter() - began
        if any(
            candidate.item_id in seen or candidate.item_id not in catalog_ids for candidate in pool
        ):
            raise ValueError("Diagnostic pool contains seen or catalog-ineligible items.")
        began = perf_counter()
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
        feature_seconds += perf_counter() - began
        labels = np.array([row["label"] for row in rows], dtype=np.int8)
        if int(labels.sum()) != request["target_in_pool"]:
            raise ValueError("Diagnostic target label differs from request pool flag.")
        began = perf_counter()
        if rows:
            item_ids = np.array([row["item_id"] for row in rows], dtype=str)
            scores = model.score(feature_matrix(pd.DataFrame(rows)))
            learned = positive_rank(scores, item_ids, labels)
            baseline = int(np.flatnonzero(labels == 1)[0] + 1) if labels.sum() else None
        else:
            learned = baseline = None
            empty += 1
        scoring_seconds += perf_counter() - began
        totals.add(pool_size=len(pool), rrf_rank=baseline, learned_rank=learned)
        if position % 500 == 0 or position == len(targets):
            print(f"  diagnostic fold {index}: {position:,}/{len(targets):,}", flush=True)
    reference_totals = reference_row["totals"]["1000"]
    if (
        totals.requests != fold["warm_target_users"]
        or totals.in_pool != reference_totals["hits"]
        or totals.candidates != reference_totals["candidate_count"]
        or empty != reference_totals["empty_requests"]
    ):
        raise ValueError("Diagnostic same-pool counts differ from frozen M7 reference.")
    return {
        "fold_index": index,
        "cutoff": cutoff,
        "metrics": totals.as_dict(),
        "empty_requests": empty,
        "fit_seconds": fit_seconds,
        "retrieval_seconds": retrieval_seconds,
        "feature_seconds": feature_seconds,
        "scoring_seconds": scoring_seconds,
    }


def run_diagnostic(args: argparse.Namespace) -> None:
    manifest, configs, identity, reference_rows = input_identity(args)
    verify_fold_files(manifest, args.fold_dir, args.max_fold)
    quality = validate_development_data(args, identity)
    _, lock = require_development_and_lock(args, identity)
    pairs, training_counts = training_samples(args, quality, [1, 2, 3, 4])
    model = PairwiseRanker.fit(
        pairs, alpha=lock["selected_alpha"], max_iterations=POLICY["max_iterations"]
    )
    model_record = {
        "weights": model.weights.tolist(),
        "scales": model.scales.tolist(),
        "alpha": model.alpha,
        "iterations": model.iterations,
        "converged": model.converged,
        "training_counts": training_counts,
    }
    expected = {
        "benchmark": "pairwise-ranker-diagnostic-v1",
        **identity,
        "selection_lock_sha256": sha256_file(args.selection_lock),
        "selected_alpha": model.alpha,
        "model_sha256": digest_json(model_record),
    }
    if args.diagnostic_artifact.exists():
        artifact = read_validated_artifact(args.diagnostic_artifact, expected)
        indices = [row["fold_index"] for row in artifact.get("folds", [])]
        if indices != list(range(5, 5 + len(indices))) or len(indices) > 5:
            raise ValueError("Ranker diagnostic artifact has invalid fold order.")
    else:
        artifact = {
            **expected,
            "role": "post-selection diagnostic; not blind validation",
            "model": model_record,
            "folds": [],
            "complete": False,
        }
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
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == 5
        write_json_atomic(args.diagnostic_artifact, artifact)
        print(f"Saved diagnostic fold {index}", flush=True)
    print(f"Saved {args.diagnostic_artifact}", flush=True)


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
        "--development-artifact",
        type=Path,
        default=Path("benchmarks/ranking/ranker_development_v1.json"),
    )
    parser.add_argument(
        "--selection-lock",
        type=Path,
        default=Path("benchmarks/ranking/ranker_selection_lock_v1.json"),
    )
    parser.add_argument(
        "--diagnostic-artifact",
        type=Path,
        default=Path("benchmarks/ranking/ranker_diagnostic_v1.json"),
    )
    parser.add_argument("--max-fold", type=int, default=9)
    args = parser.parse_args()
    if args.phase == "development":
        run_development(args)
    elif args.phase == "lock":
        run_lock(args)
    else:
        if not 5 <= args.max_fold <= 9:
            raise ValueError("Diagnostic max fold must be in 5–9.")
        run_diagnostic(args)


if __name__ == "__main__":
    main()
