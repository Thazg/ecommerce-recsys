"""Profile exact Two-Tower retrieval before the ANN feasibility screen."""

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
from ecommerce_recsys.evaluation.candidates import validate_targets
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.retrieval.two_tower import TwoTowerRetriever

POLICY = {
    "protocol": "m9-exact-cost-profile-v1",
    "folds": [1, 2, 3, 4],
    "cohort": "warm",
    "model": "selected-m8-two-tower",
    "model_config": {"dimension": 128, "max_history": 50},
    "training": {"epochs": 3, "negatives": 5, "batch_size": 1024, "seed": 42},
    "limit": 1000,
    "sample_size_per_fold": 1000,
    "strata": "four contiguous quartiles after sorting by full seen-history length and user ID",
    "seed": 42,
    "repetitions": 3,
    "gate_exact_p95_ms": 10.0,
    "percentile": "linear interpolation over all 3000 measured calls per fold",
    "warmup": "one call for each selected request before timing",
    "threads": 1,
}
PUBLISHED_TWO_TOWER_LOCK_SHA256 = "0f851bde574ece8d3e762a4f9d21a4297868ca1af1bf775b193163ee19de97db"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _source_sha256(root: Path) -> str:
    paths = [
        root / "scripts/profile_exact_retrieval.py",
        root / "src/ecommerce_recsys/retrieval/base.py",
        root / "src/ecommerce_recsys/retrieval/two_tower.py",
        root / "src/ecommerce_recsys/evaluation/latency.py",
        root / "src/ecommerce_recsys/evaluation/candidates.py",
        root / "src/ecommerce_recsys/evaluation/numeric_threads.py",
        root / "src/ecommerce_recsys/data/rolling_provenance.py",
        root / "src/ecommerce_recsys/data/splitting.py",
        root / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def _sample_indices(
    targets: pd.DataFrame, histories: dict[str, tuple[str, ...]], *, seed: int, size: int
) -> np.ndarray:
    """Sample equally from deterministic full-history-length quartiles."""
    if size <= 0 or size > len(targets) or size % 4:
        raise ValueError("Sample size must be positive, divisible by four, and within targets.")
    users = targets["user_id"].astype(str).tolist()
    order = sorted(range(len(users)), key=lambda i: (len(set(histories[users[i]])), users[i]))
    strata = np.array_split(np.asarray(order, dtype=np.int64), 4)
    rng = np.random.default_rng(seed)
    count = size // 4
    if any(len(stratum) < count for stratum in strata):
        raise ValueError("A history-length quartile is too small for the fixed sample.")
    selected = np.concatenate(
        [rng.choice(stratum, size=count, replace=False) for stratum in strata]
    )
    return np.sort(selected)


def _results_sha256(rows: list[dict]) -> str:
    return _canonical_sha256(rows)


def _save(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact["results_sha256"] = _results_sha256(artifact["results"])
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def _validate_checkpoint(artifact: dict, identity: dict) -> None:
    if any(artifact.get(key) != value for key, value in identity.items()):
        raise ValueError("Exact retrieval profile checkpoint has different input, code or policy.")
    rows = artifact.get("results")
    if not isinstance(rows, list) or artifact.get("results_sha256") != _results_sha256(rows):
        raise ValueError("Exact retrieval profile checkpoint results fail their fingerprint.")
    folds = [row.get("fold_index") for row in rows if isinstance(row, dict)]
    if len(folds) != len(rows) or folds != POLICY["folds"][: len(folds)]:
        raise ValueError("Exact retrieval profile checkpoint has invalid or duplicate folds.")
    if artifact.get("completed_folds") != folds or artifact.get("complete") != (
        folds == POLICY["folds"]
    ):
        raise ValueError(
            "Exact retrieval profile checkpoint completeness metadata is inconsistent."
        )
    expected_decision = "pending"
    if folds == POLICY["folds"]:
        expected_decision = (
            "no-go: exact retrieval below cost trigger"
            if all(row["latency"]["latency_p95_ms"] <= POLICY["gate_exact_p95_ms"] for row in rows)
            else "proceed to ANN compatibility pilot"
        )
    if artifact.get("decision") != expected_decision:
        raise ValueError(
            "Exact retrieval profile checkpoint decision is inconsistent with results."
        )


def _profile_fold(interactions: pd.DataFrame, fold: dict, fold_path: Path) -> dict:
    import torch

    train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]].copy()
    train["user_id"] = train["user_id"].astype(str)
    train["item_id"] = train["item_id"].astype(str)
    train = train.sort_values(["timestamp", "user_id", "item_id"], kind="mergesort")
    targets = pd.read_parquet(fold_path / "warm_targets.parquet")
    catalog = pd.read_parquet(fold_path / "items_train.parquet")
    validate_targets(train, targets, "warm")
    ids = set(targets["user_id"].astype(str))
    history_rows = train.loc[train["user_id"].isin(ids)]
    histories = {
        user: tuple(group["item_id"]) for user, group in history_rows.groupby("user_id", sort=False)
    }
    selected = _sample_indices(
        targets,
        histories,
        seed=POLICY["seed"] + fold["fold_index"],
        size=POLICY["sample_size_per_fold"],
    )
    contexts = [
        RetrievalContext(
            str(targets.iloc[i]["user_id"]), histories[str(targets.iloc[i]["user_id"])]
        )
        for i in selected
    ]
    sample_sha256 = _canonical_sha256(
        [(str(targets.iloc[i]["user_id"]), str(targets.iloc[i]["item_id"])) for i in selected]
    )
    source = TwoTowerRetriever(catalog).fit(
        train,
        **POLICY["model_config"],
        **POLICY["training"],
    )
    if source.item_vectors is None or source.model is None:
        raise ValueError("Selected Two-Tower could not be fitted for exact retrieval profiling.")
    source.generate(contexts[0], POLICY["limit"])
    for context in contexts[1:]:
        source.generate(context, POLICY["limit"])
    latencies: list[float] = []
    rng = np.random.default_rng(POLICY["seed"] + fold["fold_index"])
    for repeat in range(POLICY["repetitions"]):
        for index in rng.permutation(len(contexts)):
            started = perf_counter()
            source.generate(contexts[int(index)], POLICY["limit"])
            latencies.append(perf_counter() - started)
        print(f"    fold {fold['fold_index']} timing repeat {repeat + 1}/3", flush=True)
    return {
        "fold_index": fold["fold_index"],
        "train_cutoff": fold["train_cutoff"],
        "evaluation_users": len(targets),
        "catalog_items": len(source.catalog),
        "sample_size": len(contexts),
        "sample_sha256": sample_sha256,
        "fit_seconds": source.fit_seconds,
        "item_vector_bytes": source.item_vector_bytes,
        "latency": latency_metrics(latencies),
        "latency_scope": "one warm exact Two-Tower generate(context, limit=1000) call after warmup",
        "torch_threads": torch.get_num_threads(),
    }


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument(
        "--two-tower-lock",
        type=Path,
        default=Path("benchmarks/retrieval/m8_selection_lock_v1.json"),
    )
    parser.add_argument(
        "--two-tower-development",
        type=Path,
        default=Path("benchmarks/retrieval/two_tower_sweep_v1.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/retrieval/m9_profile_v1.json")
    )
    parser.add_argument("--max-fold", type=int, default=4)
    args = parser.parse_args()
    if args.max_fold not in POLICY["folds"]:
        raise ValueError("Exact retrieval profile permits only development folds 1-4.")
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    lock = json.loads(args.two_tower_lock.read_text(encoding="utf-8"))
    if sha256_file(args.two_tower_lock) != PUBLISHED_TWO_TOWER_LOCK_SHA256:
        raise ValueError(
            "Exact retrieval profile requires the published Two-Tower selection lock bytes."
        )
    if (
        manifest.get("protocol_version") != "rolling-temporal"
        or len(manifest.get("folds", [])) != 9
    ):
        raise ValueError("Exact retrieval profile requires the complete rolling manifest.")
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Exact retrieval input interactions differ from the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir)
    if (
        lock.get("protocol_version") != "m8-rolling-v1"
        or lock.get("two_tower", {}).get("selected_config") != {"dimension": 128, "max_history": 50}
        or lock["two_tower"].get("manifest_sha256") != manifest_fingerprint(manifest)
        or lock["two_tower"].get("input_sha256") != manifest["source_sha256"]
        or lock["two_tower"].get("development_artifact_sha256")
        != sha256_file(args.two_tower_development)
    ):
        raise ValueError(
            "Exact retrieval profile requires the published Two-Tower selection and development evidence."
        )
    import torch

    runtime = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "torch": torch.__version__,
    }
    if runtime != lock["runtime"]:
        raise ValueError(
            "Exact retrieval profile runtime differs from the locked Two-Tower runtime."
        )
    identity = {
        "protocol_version": POLICY["protocol"],
        "phase": "development-exact-cost",
        "blind_holdout": False,
        "expected_folds": POLICY["folds"],
        "policy": POLICY,
        "policy_sha256": _canonical_sha256(POLICY),
        "runner_sha256": _source_sha256(root),
        "manifest_sha256": manifest_fingerprint(manifest),
        "input_sha256": manifest["source_sha256"],
        "m8_lock_sha256": sha256_file(args.two_tower_lock),
        "m8_development_sha256": sha256_file(args.two_tower_development),
        "runtime": runtime,
    }
    artifact = {
        **identity,
        "results": [],
        "completed_folds": [],
        "complete": False,
        "decision": "pending",
    }
    if args.output.exists():
        artifact = json.loads(args.output.read_text(encoding="utf-8"))
        _validate_checkpoint(artifact, identity)
    completed = set(artifact["completed_folds"])
    interactions = pd.read_parquet(args.input_path)
    if interactions[["user_id", "item_id", "timestamp"]].isna().any().any():
        raise ValueError("Exact retrieval input interactions contain null IDs or timestamps.")
    for fold in manifest["folds"][: args.max_fold]:
        if fold["fold_index"] in completed:
            continue
        print(f"Exact retrieval profile fold {fold['fold_index']}: fitting", flush=True)
        row = _profile_fold(interactions, fold, args.fold_dir / f"fold_{fold['fold_index']:02d}")
        artifact["results"].append(row)
        artifact["completed_folds"] = sorted(row["fold_index"] for row in artifact["results"])
        artifact["complete"] = artifact["completed_folds"] == POLICY["folds"]
        if artifact["complete"]:
            artifact["decision"] = (
                "no-go: exact retrieval below cost trigger"
                if all(
                    r["latency"]["latency_p95_ms"] <= POLICY["gate_exact_p95_ms"]
                    for r in artifact["results"]
                )
                else "proceed to ANN compatibility pilot"
            )
        _save(args.output, artifact)
        print(
            f"  fold {fold['fold_index']} p95={row['latency']['latency_p95_ms']:.3f} ms; saved {args.output}",
            flush=True,
        )
    print(
        json.dumps(
            {"completed_folds": artifact["completed_folds"], "decision": artifact["decision"]}
        )
    )


if __name__ == "__main__":
    main()
