"""Compare exact Two-Tower and ALS candidate recall on rolling folds."""

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
from ecommerce_recsys.evaluation.candidates import evaluate_candidate_sources
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.retrieval.mf_retriever import MFRetriever
from ecommerce_recsys.retrieval.two_tower import TwoTowerRetriever

TWO_TOWER_CONFIGS = tuple(
    {"dimension": dimension, "max_history": history}
    for dimension in (64, 128)
    for history in (20, 50)
)
ALS_CONFIGS = (
    {"factors": 32, "iterations": 20, "regularization": 0.01},
    {"factors": 64, "iterations": 20, "regularization": 0.01},
    {"factors": 128, "iterations": 20, "regularization": 0.01},
    {"factors": 64, "iterations": 20, "regularization": 0.001},
    {"factors": 64, "iterations": 20, "regularization": 0.1},
    {"factors": 64, "iterations": 10, "regularization": 0.01},
    {"factors": 64, "iterations": 40, "regularization": 0.01},
    {"factors": 128, "iterations": 40, "regularization": 0.01},
)
M7_REFERENCE_ALS_CONFIG = {"factors": 128, "iterations": 40, "regularization": 0.01}


def _diagnostic_configs(model: str, locked: dict) -> tuple[dict, ...]:
    if model != "als":
        return (locked,)
    if locked == M7_REFERENCE_ALS_CONFIG:
        return (locked,)
    return (locked, M7_REFERENCE_ALS_CONFIG)


POLICY = {
    "protocol": "rolling-temporal",
    "cohort": "warm",
    "budgets": [100, 500, 1000],
    "selection": "pooled Recall@1000, then Recall@100, then lower parameter count",
    "training_examples": "first occurrence of each item after strictly earlier user history",
    "same_timestamp": "exclude timestamp peers from history and from negative candidates",
    "history_semantics": "latest occurrence per item, preserving recency, truncated to max_history",
    "negative_sampling": "independent uniform draws with replacement from train-catalog items first seen strictly before the positive timestamp; exclude full prior user history and every same-timestamp item; skip examples with no eligible negative",
    "seed": 42,
    "threads": 1,
    "epochs": 3,
    "negatives": 5,
    "training_logit_scale": 20.0,
    "batch_size": 1024,
    "optimizer": "Adam lr=0.003 for MLPs, SparseAdam lr=0.003 for embedding tables",
    "device": "cpu, one torch thread, deterministic algorithms enabled",
    "history_tower": "mean of shared item-id embeddings over recent distinct items, then MLP",
    "item_tower": "item-id and as-of-cutoff category embeddings concatenated, then MLP",
    "scoring": "L2-normalized user/item vectors with dot product",
    "event_weighting": "equal across interaction types",
}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _runner_sha256(root: Path) -> str:
    paths = sorted((root / "src/ecommerce_recsys").rglob("*.py")) + [
        root / "scripts/benchmark_two_tower.py",
        root / "scripts/lock_two_tower_configs.py",
        root / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def _config_key(config: dict) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _is_complete(
    results: list[dict], configurations: list[dict], expected_folds: list[int]
) -> bool:
    expected = {(_config_key(config), fold) for config in configurations for fold in expected_folds}
    observed = {(_config_key(row["config"]), row["fold_index"]) for row in results}
    return observed == expected


def _completed_folds(
    results: list[dict], configurations: list[dict], expected_folds: list[int]
) -> list[int]:
    observed = {(_config_key(row["config"]), row["fold_index"]) for row in results}
    config_keys = {_config_key(config) for config in configurations}
    return [
        fold
        for fold in expected_folds
        if all((config_key, fold) in observed for config_key in config_keys)
    ]


def _save(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact["results_sha256"] = _results_sha256(artifact)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def _results_sha256(artifact: dict) -> str:
    return hashlib.sha256(
        json.dumps(artifact.get("results", []), sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_checkpoint(artifact: dict, identity: dict) -> None:
    if any(artifact.get(key) != value for key, value in identity.items()):
        raise ValueError(
            "Existing Two-Tower checkpoint has different data, code, config or policy."
        )
    if artifact.get("results_sha256") != _results_sha256(artifact):
        raise ValueError(
            "Existing Two-Tower checkpoint result rows fail their content fingerprint."
        )
    expected_configs = {_config_key(config) for config in identity["configurations"]}
    expected_folds = identity["expected_folds"]
    seen = set()
    for row in artifact.get("results", []):
        if not isinstance(row.get("config"), dict) or not isinstance(row.get("fold_index"), int):
            raise ValueError("Existing Two-Tower checkpoint has an invalid comparison row.")
        key = (_config_key(row.get("config")), row.get("fold_index"))
        if (
            key in seen
            or key[0] not in expected_configs
            or key[1] not in expected_folds
            or row.get("phase") != identity["phase"]
        ):
            raise ValueError(
                "Existing Two-Tower checkpoint has an invalid or duplicate comparison row."
            )
        seen.add(key)
    completed_folds = _completed_folds(
        artifact.get("results", []), identity["configurations"], expected_folds
    )
    complete = _is_complete(artifact.get("results", []), identity["configurations"], expected_folds)
    if (
        artifact.get("completed_folds") != completed_folds
        or artifact.get("complete") is not complete
    ):
        raise ValueError("Existing Two-Tower checkpoint completeness metadata is inconsistent.")


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("two_tower", "als"), required=True)
    parser.add_argument("--phase", choices=("development", "diagnostic"), default="development")
    parser.add_argument("--max-fold", type=int)
    parser.add_argument("--only-config", help="Run one JSON configuration for a pilot or resume.")
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--locked-config", help="JSON configuration required for diagnostic folds.")
    parser.add_argument("--selection-lock", type=Path)
    parser.add_argument("--development-artifact", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    code_digest = _runner_sha256(root)
    try:
        import torch

        torch_version = torch.__version__
    except ImportError as error:
        if args.model == "two_tower":
            raise RuntimeError(
                'Install with `pip install -e ".[two-tower]"` in the project environment.'
            ) from error
        torch_version = None
    runtime = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "torch": torch_version,
    }

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_version") != "rolling-temporal" or len(manifest["folds"]) != 9:
        raise ValueError("Two-Tower requires the complete nine-fold rolling manifest.")
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Input interactions do not match the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir)
    maximum = (
        args.max_fold if args.max_fold is not None else (4 if args.phase == "development" else 9)
    )
    lower = 1 if args.phase == "development" else 5
    if maximum < lower or maximum > (4 if args.phase == "development" else 9):
        raise ValueError("Fold bound is outside the selected Two-Tower phase.")
    if args.phase == "development":
        fold_range = range(1, maximum + 1)
        expected_folds = list(range(1, 5))
    else:
        fold_range = range(5, maximum + 1)
        expected_folds = list(range(5, 10))
    configs = TWO_TOWER_CONFIGS if args.model == "two_tower" else ALS_CONFIGS
    selection_lock_sha256 = None
    development_artifact_sha256 = None
    if args.only_config:
        selected = json.loads(args.only_config)
        if selected not in configs:
            raise ValueError("Pilot configuration is outside the predeclared search grid.")
        configs = (selected,)
    if args.phase == "diagnostic":
        if args.selection_lock is None or args.development_artifact is None:
            raise ValueError(
                "Diagnostic folds require a selection lock and its development artifact."
            )
        lock = json.loads(args.selection_lock.read_text(encoding="utf-8"))
        selection_script = root / "scripts/lock_two_tower_configs.py"
        if (
            lock.get("protocol_version") != "m8-rolling-v1"
            or lock.get("blind_holdout") is not False
            or lock.get("selection_script_sha256") != sha256_file(selection_script)
            or lock.get("policy_sha256") != _canonical_sha256(POLICY)
            or lock.get("runner_sha256") != code_digest
            or lock.get("runtime") != runtime
        ):
            raise ValueError(
                "Two-Tower selection lock has an unsupported protocol or stale selector."
            )
        lock_key = "two_tower" if args.model == "two_tower" else "als_candidate_recall"
        lock_entry = lock[lock_key]
        development_artifact_sha256 = sha256_file(args.development_artifact)
        if development_artifact_sha256 != lock_entry["development_artifact_sha256"]:
            raise ValueError("Development artifact differs from the artifact bound into the lock.")
        development_artifact = json.loads(args.development_artifact.read_text(encoding="utf-8"))
        if (
            development_artifact.get("model") != args.model
            or development_artifact.get("phase") != "development"
            or development_artifact.get("complete") is not True
            or development_artifact.get("expected_folds") != list(range(1, 5))
            or development_artifact.get("policy") != POLICY
            or development_artifact.get("policy_sha256") != _canonical_sha256(POLICY)
            or development_artifact.get("runner_sha256") != code_digest
            or development_artifact.get("runtime") != runtime
            or development_artifact.get("results_sha256") != _results_sha256(development_artifact)
        ):
            raise ValueError(
                "Development artifact policy, runner, runtime or completeness differs."
            )
        from scripts.lock_two_tower_configs import _select

        expected_lock_entry = _select(
            args.development_artifact,
            args.model,
            TWO_TOWER_CONFIGS if args.model == "two_tower" else ALS_CONFIGS,
        )
        if lock_entry != expected_lock_entry:
            raise ValueError(
                "Selection lock does not reproduce from its bound development artifact."
            )
        if (
            lock_entry.get("policy_sha256") != _canonical_sha256(POLICY)
            or lock_entry.get("runner_sha256") != code_digest
            or lock_entry.get("runtime") != runtime
        ):
            raise ValueError(
                "Diagnostic runner does not match the locked Two-Tower policy or runtime."
            )
        if lock_entry["manifest_sha256"] != manifest_fingerprint(manifest) or lock_entry[
            "input_sha256"
        ] != sha256_file(args.input_path):
            raise ValueError(
                "Two-Tower selection lock uses a different dataset or rolling manifest."
            )
        selection_lock_sha256 = sha256_file(args.selection_lock)
        locked = lock_entry["selected_config"]
        if args.locked_config and json.loads(args.locked_config) != locked:
            raise ValueError(
                "Requested diagnostic config differs from the Two-Tower selection lock."
            )
        if locked not in (TWO_TOWER_CONFIGS if args.model == "two_tower" else ALS_CONFIGS):
            raise ValueError("Locked configuration is outside the predeclared development grid.")
        configs = _diagnostic_configs(args.model, locked)
    output = args.output or Path(f"benchmarks/retrieval/{args.model}_{args.phase}_v1.json")
    input_hash = sha256_file(args.input_path)
    manifest_hash = manifest_fingerprint(manifest)
    identity = {
        "model": args.model,
        "phase": args.phase,
        "blind_holdout": False,
        "result_validity": (
            "development only" if args.phase == "development" else "post-selection diagnostic"
        ),
        "configurations": list(configs),
        "expected_folds": expected_folds,
        "policy": POLICY,
        "policy_sha256": _canonical_sha256(POLICY),
        "input_sha256": input_hash,
        "manifest_sha256": manifest_hash,
        "runner_sha256": code_digest,
        "selection_lock_sha256": selection_lock_sha256,
        "development_artifact_sha256": development_artifact_sha256,
        "runtime": runtime,
    }
    artifact = {**identity, "results": [], "completed_folds": [], "complete": False}
    if output.exists():
        artifact = json.loads(output.read_text(encoding="utf-8"))
        _validate_checkpoint(artifact, identity)
    completed = {
        (_config_key(row["config"]), row["fold_index"]) for row in artifact.get("results", [])
    }
    for fold_index in fold_range:
        fold = manifest["folds"][fold_index - 1]
        fold_path = args.fold_dir / f"fold_{fold_index:02d}"
        train = pd.read_parquet(args.input_path)
        train = train.loc[train["timestamp"] <= fold["train_cutoff"]].copy()
        train["user_id"] = train["user_id"].astype(str)
        train["item_id"] = train["item_id"].astype(str)
        train = train.sort_values(["timestamp", "user_id", "item_id"], kind="mergesort")
        targets = pd.read_parquet(fold_path / "warm_targets.parquet")
        catalog = pd.read_parquet(fold_path / "items_train.parquet")
        for config in configs:
            key = (_config_key(config), fold_index)
            if key in completed:
                continue
            if args.model == "two_tower":
                source = TwoTowerRetriever(catalog).fit(
                    train,
                    dimension=config["dimension"],
                    max_history=config["max_history"],
                    epochs=POLICY["epochs"],
                    negatives=POLICY["negatives"],
                    batch_size=POLICY["batch_size"],
                    seed=POLICY["seed"],
                )
                model_cost = {
                    "fit_seconds": source.fit_seconds,
                    "training_seconds": source.training_seconds,
                    "parameter_bytes": source.parameter_bytes,
                    "item_vector_bytes": source.item_vector_bytes,
                    "estimated_resident_model_bytes": source.parameter_bytes
                    + source.item_vector_bytes,
                    "train_examples": source.train_examples,
                    "generated_examples": source.generated_examples,
                    "skipped_examples_no_causal_negative": source.skipped_examples,
                    "skipped_example_rate": source.skipped_example_rate,
                    "skipped_batch_sampler_attempts": source.skipped_batch_sampler_attempts,
                    "catalog_items": len(source.catalog),
                    "epochs": POLICY["epochs"],
                    "negative_samples": POLICY["negatives"],
                }
            else:
                model = MatrixFactorizationRecommender(**config, random_state=POLICY["seed"])
                fit_start = perf_counter()
                model.fit(train)
                source = MFRetriever(model, catalog["item_id"].astype(str))
                model_cost = {
                    "fit_seconds": perf_counter() - fit_start,
                    "factor_array_bytes": model.factor_memory_bytes,
                    "catalog_items": len(source.catalog),
                }
            metrics = evaluate_candidate_sources(train, targets, [source], [], cohort="warm")[0]
            artifact["results"].append(
                {
                    "phase": args.phase,
                    "fold_index": fold_index,
                    "config": config,
                    "evaluation_users": metrics["evaluation_users"],
                    "reachable_targets": metrics["reachable_targets"],
                    "metrics": metrics["metrics"],
                    "totals": metrics["totals"],
                    "latency": {
                        key: metrics[key]
                        for key in ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms")
                    },
                    "latency_scope": metrics["latency_scope"],
                    "model_cost": model_cost,
                }
            )
            artifact["completed_folds"] = _completed_folds(
                artifact["results"], identity["configurations"], expected_folds
            )
            artifact["complete"] = _is_complete(
                artifact["results"], identity["configurations"], expected_folds
            )
            _save(output, artifact)
            print(
                f"{args.phase} fold {fold_index} {config}: "
                f"Recall@1000={metrics['metrics']['Recall@1000']:.6f}; saved {output}",
                flush=True,
            )
    print(
        json.dumps(
            {
                "artifact": str(output),
                "comparisons": len(artifact["results"]),
                "completed_folds": artifact["completed_folds"],
                "complete": artifact["complete"],
            }
        )
    )


if __name__ == "__main__":
    main()
