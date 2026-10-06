"""Evaluate M4–M6 recommenders on identical rolling, causal warm-user folds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.benchmark import evaluate_recommender
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from ecommerce_recsys.recommendation.category_popularity import CategoryPopularityRecommender
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.recommendation.random_recommender import RandomRecommender
from ecommerce_recsys.recommendation.recent_popularity import RecentPopularityRecommender

MODELS = (
    "random",
    "global_popularity",
    "recent_popularity",
    "category_popularity",
    "item_knn",
    "als",
)
K_VALUES = (5, 10, 20)


def make_model(name: str):
    """Use one fixed historical configuration for each model across all folds."""
    return {
        "random": lambda: RandomRecommender(seed=42),
        "global_popularity": PopularityRecommender,
        "recent_popularity": lambda: RecentPopularityRecommender(window_days=30),
        "category_popularity": CategoryPopularityRecommender,
        "item_knn": lambda: ItemKNNRecommender(
            n_neighbors=20, min_item_interactions=5, shrinkage_lambda=100.0
        ),
        "als": lambda: MatrixFactorizationRecommender(
            factors=128, iterations=20, regularization=0.01, random_state=42
        ),
    }[name]()


def summarize(results: list[dict]) -> dict:
    """Pool per-fold rates by evaluated user-window count."""
    by_model: dict[str, list[dict]] = {}
    for result in results:
        by_model.setdefault(result["model"], []).append(result)
    summary = {}
    for model, rows in by_model.items():
        total = sum(row["evaluation_users"] for row in rows)
        metric_names = [
            name for name in rows[0]["metrics"] if name.startswith(("HR@", "MRR@", "NDCG@"))
        ]
        summary[model] = {
            "folds": len(rows),
            "user_window_targets": total,
            "pooled_metrics": {
                name: round(
                    sum(row["evaluation_users"] * row["metrics"][name] for row in rows) / total,
                    6,
                )
                for name in metric_names
            },
        }
    return summary


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/rolling/results.json"))
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument(
        "--max-fold",
        type=int,
        default=9,
        help="Stop at fold 4 while tuning; folds 5-9 require completed sweep artifacts.",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["protocol_version"] != "rolling-temporal":
        raise ValueError("Expected rolling temporal manifest.")
    if not 1 <= args.max_fold <= 9:
        raise ValueError("max-fold must be between 1 and 9.")
    fingerprint = manifest_fingerprint(manifest)
    if args.max_fold > 4:
        require_completed_sweeps(args.output.parent, manifest)
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Input interactions do not match the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir, args.max_fold)
    interactions = pd.read_parquet(args.input_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        artifact = json.loads(args.output.read_text(encoding="utf-8"))
        if (
            artifact.get("source_sha256") != manifest["source_sha256"]
            or artifact.get("manifest_sha256") != fingerprint
        ):
            raise ValueError("Existing results belong to a different rolling dataset.")
    else:
        artifact = {
            "protocol_version": manifest["protocol_version"],
            "source_sha256": manifest["source_sha256"],
            "manifest_sha256": fingerprint,
            "role": "diagnostic, configs transferred from historical experiments",
            "blind_holdout": False,
            "cohort": "warm users with >=1 earlier interaction and an unseen window target",
            "unit": "user-window; a person may appear in several folds",
            "k_values": list(K_VALUES),
            "results": [],
        }
    artifact["role"] = "diagnostic, configs transferred from historical experiments"
    artifact["blind_holdout"] = False
    artifact["protocol_version"] = manifest["protocol_version"]
    artifact["numeric_threads"] = 1

    done = {(row["model"], row["fold_index"]) for row in artifact["results"]}
    for fold in manifest["folds"][: args.max_fold]:
        fold_index = fold["fold_index"]
        names = [name for name in args.models if (name, fold_index) not in done]
        if not names:
            continue
        print(f"Fold {fold_index}: loading shared snapshot", flush=True)
        train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]]
        path = args.fold_dir / f"fold_{fold_index:02d}"
        targets = pd.read_parquet(path / "warm_targets.parquet")
        catalog = pd.read_parquet(path / "items_train.parquet")
        if len(targets) != fold["warm_target_users"] or len(catalog) != fold["train_catalog_items"]:
            raise ValueError(f"Fold {fold_index} files do not match manifest.")
        for name in names:
            print(f"  {name}: fit + evaluate {len(targets):,} users", flush=True)
            metrics = evaluate_recommender(
                make_model(name),
                train,
                targets,
                items=catalog,
                k_values=K_VALUES,
                total_catalog_items=len(catalog),
                train_cutoff=fold["train_cutoff"],
            )
            row = {
                "fold_index": fold_index,
                "model": name,
                "evaluation_users": len(targets),
                "metrics": metrics,
            }
            artifact["results"].append(row)
            artifact["summary"] = summarize(artifact["results"])
            pending = args.output.with_suffix(".json.tmp")
            pending.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
            pending.replace(args.output)
            print(f"    HR@20={metrics['HR@20']:.6f}", flush=True)
    pending = args.output.with_suffix(".json.tmp")
    pending.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    pending.replace(args.output)
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
