"""Tune ItemKNN or ALS on rolling folds 1–4, then evaluate the winner on 5–9."""

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
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender

K_VALUES = (5, 10, 20)
LAMBDAS = (0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
ALS_CONFIGS = (
    (32, 20, 0.01),
    (64, 20, 0.01),
    (128, 20, 0.01),
    (64, 20, 0.001),
    (64, 20, 0.1),
    (64, 10, 0.01),
    (64, 40, 0.01),
    (128, 40, 0.01),
)


def _key(config: dict) -> str:
    return json.dumps(config, sort_keys=True)


def _configs(model: str) -> list[dict]:
    if model == "item_knn":
        return [{"shrinkage_lambda": value} for value in LAMBDAS]
    return [
        {"factors": factors, "iterations": iterations, "regularization": regularization}
        for factors, iterations, regularization in ALS_CONFIGS
    ]


def _score(rows: list[dict], config: dict) -> tuple[float, float]:
    matched = [row for row in rows if row["config"] == config and row["fold_index"] <= 4]
    total = sum(row["evaluation_users"] for row in matched)
    if len(matched) != 4 or total == 0:
        raise ValueError("All four tuning folds must be complete before selection.")
    return tuple(
        sum(row["evaluation_users"] * row["metrics"][metric] for row in matched) / total
        for metric in ("HR@20", "NDCG@20")
    )


def _save(path: Path, artifact: dict) -> None:
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    pending.replace(path)


def _validate_final_checkpoint(artifact: dict, selected: dict) -> None:
    """Do not combine final-fold scores from different sweep selections."""
    final = [row for row in artifact["results"] if row.get("phase") == "final"]
    if any(row.get("config") != selected for row in final):
        raise ValueError(
            "Checkpoint contains final-fold results from another selected configuration. "
            "Use a fresh output directory for a changed sweep."
        )
    indices = [row["fold_index"] for row in final]
    if len(indices) != len(set(indices)) or any(index not in range(5, 10) for index in indices):
        raise ValueError("Checkpoint contains invalid or duplicate final-fold results.")
    if artifact.get("final_summary") and len(final) != 5:
        raise ValueError("Checkpoint has a final summary but incomplete final folds.")


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("item_knn", "als"), required=True)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/rolling"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["protocol_version"] != "rolling-temporal":
        raise ValueError("Expected rolling temporal manifest.")
    fingerprint = manifest_fingerprint(manifest)
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Input interactions do not match manifest.")
    if len(manifest["folds"]) != 9:
        raise ValueError("Expected nine rolling folds.")
    verify_fold_files(manifest, args.fold_dir)
    interactions = pd.read_parquet(args.input_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.model}_sweep.json"
    if output.exists():
        artifact = json.loads(output.read_text(encoding="utf-8"))
        if (
            artifact.get("source_sha256") != manifest["source_sha256"]
            or artifact.get("manifest_sha256") != fingerprint
            or artifact.get("protocol_version") != manifest["protocol_version"]
            or artifact.get("model") != args.model
        ):
            raise ValueError("Existing sweep belongs to a different dataset, protocol, or model.")
    else:
        artifact = {
            "protocol_version": manifest["protocol_version"],
            "source_sha256": manifest["source_sha256"],
            "manifest_sha256": fingerprint,
            "model": args.model,
            "blind_holdout": False,
            "holdout_disclosure": (
                "Reference HR/NDCG on folds 5-9 was viewed before this rolling sweep "
                "was locked; folds 5-9 are post-selection diagnostics, not a blind test."
            ),
            "selection_folds": [1, 2, 3, 4],
            "final_folds": [5, 6, 7, 8, 9],
            "selection_metric": "pooled warm-user HR@20; NDCG@20 tie-break",
            "results": [],
        }
    artifact["blind_holdout"] = False
    artifact["protocol_version"] = manifest["protocol_version"]
    artifact["numeric_threads"] = 1
    artifact["holdout_disclosure"] = (
        "Reference HR/NDCG on folds 5-9 was viewed before this rolling sweep "
        "was locked; folds 5-9 are post-selection diagnostics, not a blind test."
    )
    configs = _configs(args.model)
    done = {(_key(row["config"]), row["fold_index"]) for row in artifact["results"]}

    for fold in manifest["folds"][:4]:
        index = fold["fold_index"]
        missing = [config for config in configs if (_key(config), index) not in done]
        if not missing:
            continue
        print(f"Tuning fold {index}: {len(missing)} configurations", flush=True)
        train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]]
        fold_path = args.fold_dir / f"fold_{index:02d}"
        targets = pd.read_parquet(fold_path / "warm_targets.parquet")
        catalog_size = len(pd.read_parquet(fold_path / "items_train.parquet", columns=["item_id"]))

        shared_knn = None
        if args.model == "item_knn":
            shared_knn = ItemKNNRecommender(
                n_neighbors=20, min_item_interactions=5, shrinkage_lambda=0.0
            )
            shared_knn.fit(train)

        for config in missing:
            print(f"  {config}", flush=True)
            if shared_knn is not None:
                shared_knn.set_shrinkage_lambda(config["shrinkage_lambda"])
                model = shared_knn
                fit = False
            else:
                model = MatrixFactorizationRecommender(**config, random_state=42)
                fit = True
            metrics = evaluate_recommender(
                model,
                train,
                targets,
                k_values=K_VALUES,
                total_catalog_items=catalog_size,
                fit=fit,
                train_cutoff=fold["train_cutoff"],
            )
            artifact["results"].append(
                {
                    "fold_index": index,
                    "config": config,
                    "evaluation_users": len(targets),
                    "metrics": metrics,
                    "phase": "selection",
                }
            )
            _save(output, artifact)
            print(f"    HR@20={metrics['HR@20']:.6f}", flush=True)

    ranked = sorted(configs, key=lambda config: _score(artifact["results"], config), reverse=True)
    selected = ranked[0]
    _validate_final_checkpoint(artifact, selected)
    artifact["selected_config"] = selected
    artifact["selection_ranking"] = [
        {
            "config": config,
            "pooled_HR@20": round(_score(artifact["results"], config)[0], 6),
            "pooled_NDCG@20": round(_score(artifact["results"], config)[1], 6),
        }
        for config in ranked
    ]
    _save(output, artifact)
    print(f"Selected {selected}", flush=True)

    for fold in manifest["folds"][4:]:
        index = fold["fold_index"]
        if (_key(selected), index) in done:
            continue
        print(f"Final fold {index}: {selected}", flush=True)
        train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]]
        fold_path = args.fold_dir / f"fold_{index:02d}"
        targets = pd.read_parquet(fold_path / "warm_targets.parquet")
        catalog_size = len(pd.read_parquet(fold_path / "items_train.parquet", columns=["item_id"]))
        if args.model == "item_knn":
            model = ItemKNNRecommender(
                n_neighbors=20,
                min_item_interactions=5,
                shrinkage_lambda=selected["shrinkage_lambda"],
            )
        else:
            model = MatrixFactorizationRecommender(**selected, random_state=42)
        metrics = evaluate_recommender(
            model,
            train,
            targets,
            k_values=K_VALUES,
            total_catalog_items=catalog_size,
            train_cutoff=fold["train_cutoff"],
        )
        artifact["results"].append(
            {
                "fold_index": index,
                "config": selected,
                "evaluation_users": len(targets),
                "metrics": metrics,
                "phase": "final",
            }
        )
        _save(output, artifact)
        print(f"  HR@20={metrics['HR@20']:.6f}", flush=True)

    final = [row for row in artifact["results"] if row["phase"] == "final"]
    total = sum(row["evaluation_users"] for row in final)
    artifact["final_summary"] = {
        "user_window_targets": total,
        "pooled_metrics": {
            name: round(
                sum(row["evaluation_users"] * row["metrics"][name] for row in final) / total,
                6,
            )
            for name in final[0]["metrics"]
            if name.startswith(("HR@", "MRR@", "NDCG@"))
        },
    }
    _save(output, artifact)
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
