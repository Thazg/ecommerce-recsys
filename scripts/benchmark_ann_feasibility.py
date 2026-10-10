"""Run the predeclared ANN speed gate against paired exact Two-Tower."""

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
from scripts.faiss_ann_adapter import FaissTwoTowerANN
from scripts.profile_exact_retrieval import (
    POLICY as PROFILE_POLICY,
)
from scripts.profile_exact_retrieval import (
    PUBLISHED_TWO_TOWER_LOCK_SHA256,
    _sample_indices,
)
from scripts.profile_exact_retrieval import (
    _source_sha256 as _profile_runner_sha256,
)
from scripts.profile_exact_retrieval import (
    _validate_checkpoint as _validate_profile,
)

CONFIGS = tuple(
    {"graph_degree": degree, "ef_construction": 200, "ef_search": effort}
    for degree in (16, 32)
    for effort in (2000, 4000)
)
POLICY = {
    "protocol": "m9-ann-fold1-pilot-v1",
    "fold": 1,
    "cohort": "warm",
    "library": "faiss-cpu HNSW inner product",
    "model_config": {"dimension": 128, "max_history": 50},
    "training": {"epochs": 3, "negatives": 5, "batch_size": 1024, "seed": 42},
    "configs": CONFIGS,
    "limit": 1000,
    "budgets": [100, 500, 1000],
    "sample_size": 1000,
    "sampling": "exact-profile history-length quartiles, seed 42+fold",
    "repetitions": 3,
    "warmup": "one paired call per selected context before timing",
    "timing_order": "seeded request permutation and seeded exact/ANN call order per repeat",
    "speed_gate": "ANN p95 <= 0.5 * paired exact p95 on every development fold",
    "early_stop": "if all four configurations fail fold 1, none can pass the all-fold speed gate",
    "threads": 1,
}


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _runner_sha256(root: Path) -> str:
    paths = [
        root / "scripts/benchmark_ann_feasibility.py",
        root / "scripts/faiss_ann_adapter.py",
        root / "scripts/profile_exact_retrieval.py",
        root / "src/ecommerce_recsys/retrieval/two_tower.py",
        root / "src/ecommerce_recsys/retrieval/base.py",
        root / "src/ecommerce_recsys/evaluation/candidates.py",
        root / "src/ecommerce_recsys/evaluation/latency.py",
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


def _config_key(config: dict) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"))


def _save(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact["results_sha256"] = _sha(artifact["results"])
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def _validate_checkpoint(artifact: dict, identity: dict) -> None:
    if any(artifact.get(key) != value for key, value in identity.items() if key != "policy") or (
        "policy" in identity and _sha(artifact.get("policy")) != _sha(identity["policy"])
    ):
        raise ValueError("ANN pilot checkpoint has different data, code, runtime or policy.")
    rows = artifact.get("results")
    if not isinstance(rows, list) or artifact.get("results_sha256") != _sha(rows):
        raise ValueError("ANN pilot checkpoint result fingerprint differs.")
    keys = [_config_key(row["config"]) for row in rows]
    expected = [_config_key(config) for config in CONFIGS]
    if keys != expected[: len(keys)]:
        raise ValueError("ANN pilot checkpoint has unexpected or duplicate configurations.")
    complete = len(rows) == len(CONFIGS)
    if artifact.get("complete") is not complete:
        raise ValueError("ANN pilot completeness metadata is inconsistent.")
    decision = "pending"
    if complete:
        decision = (
            "no-go: all configs fail fold-1 paired p95 gate"
            if all(not row["passes_speed_gate"] for row in rows)
            else "continue complete development evaluation"
        )
    if artifact.get("decision") != decision:
        raise ValueError("ANN pilot decision is inconsistent with its rows.")


def _sample_metrics(hits: dict[int, int], denominator: int) -> dict[str, float | int]:
    return {f"Recall@{budget}": hits[budget] / denominator for budget in POLICY["budgets"]}


def _measure_pair(
    exact: TwoTowerRetriever,
    ann: FaissTwoTowerANN,
    contexts: list[RetrievalContext],
    targets: list[str],
) -> dict:
    exact_latencies: list[float] = []
    ann_latencies: list[float] = []
    exact_hits = {budget: 0 for budget in POLICY["budgets"]}
    ann_hits = {budget: 0 for budget in POLICY["budgets"]}
    exact_only = {budget: 0 for budget in POLICY["budgets"]}
    ann_only = {budget: 0 for budget in POLICY["budgets"]}
    for context in contexts:
        exact.generate(context, POLICY["limit"])
        ann.generate(context, POLICY["limit"])
    rng = np.random.default_rng(42 + POLICY["fold"])
    for repeat in range(POLICY["repetitions"]):
        for index in rng.permutation(len(contexts)):
            position = int(index)
            context = contexts[position]
            pools = {}
            for name in ("exact", "ann") if rng.integers(2) == 0 else ("ann", "exact"):
                started = perf_counter()
                pools[name] = (exact if name == "exact" else ann).generate(context, POLICY["limit"])
                elapsed = perf_counter() - started
                (exact_latencies if name == "exact" else ann_latencies).append(elapsed)
            if repeat == 0:
                target = targets[position]
                for budget in POLICY["budgets"]:
                    exact_hit = target in {c.item_id for c in pools["exact"][:budget]}
                    ann_hit = target in {c.item_id for c in pools["ann"][:budget]}
                    exact_hits[budget] += exact_hit
                    ann_hits[budget] += ann_hit
                    exact_only[budget] += exact_hit and not ann_hit
                    ann_only[budget] += ann_hit and not exact_hit
        print(f"    paired timing repeat {repeat + 1}/3", flush=True)
    exact_summary = latency_metrics(exact_latencies)
    ann_summary = latency_metrics(ann_latencies)
    return {
        "sample_targets": len(contexts),
        "exact_sample_recall": _sample_metrics(exact_hits, len(contexts)),
        "ann_sample_recall": _sample_metrics(ann_hits, len(contexts)),
        "exact_hits": {str(k): v for k, v in exact_hits.items()},
        "ann_hits": {str(k): v for k, v in ann_hits.items()},
        "exact_only_hits": {str(k): v for k, v in exact_only.items()},
        "ann_only_hits": {str(k): v for k, v in ann_only.items()},
        "exact_latency": exact_summary,
        "ann_latency": ann_summary,
        "passes_speed_gate": ann_summary["latency_p95_ms"] <= 0.5 * exact_summary["latency_p95_ms"],
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
        "--profile", type=Path, default=Path("benchmarks/retrieval/m9_profile_v1.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/retrieval/m9_ann_pilot_v1.json")
    )
    args = parser.parse_args()
    import faiss
    import torch

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    lock = json.loads(args.two_tower_lock.read_text(encoding="utf-8"))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    profile_identity = {
        "protocol_version": PROFILE_POLICY["protocol"],
        "phase": "development-exact-cost",
        "blind_holdout": False,
        "expected_folds": PROFILE_POLICY["folds"],
        "policy": PROFILE_POLICY,
        "policy_sha256": _sha(PROFILE_POLICY),
        "runner_sha256": _profile_runner_sha256(root),
        "manifest_sha256": manifest_fingerprint(manifest),
        "input_sha256": manifest["source_sha256"],
        "m8_lock_sha256": sha256_file(args.two_tower_lock),
        "m8_development_sha256": sha256_file(args.two_tower_development),
        "runtime": profile.get("runtime"),
    }
    _validate_profile(profile, profile_identity)
    if (
        manifest.get("protocol_version") != "rolling-temporal"
        or len(manifest.get("folds", [])) != 9
    ):
        raise ValueError("ANN feasibility requires the full rolling manifest.")
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("ANN feasibility input differs from the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir)
    if (
        sha256_file(args.two_tower_lock) != PUBLISHED_TWO_TOWER_LOCK_SHA256
        or lock.get("two_tower", {}).get("selected_config") != POLICY["model_config"]
        or lock["two_tower"].get("development_artifact_sha256")
        != sha256_file(args.two_tower_development)
        or lock["two_tower"].get("manifest_sha256") != manifest_fingerprint(manifest)
    ):
        raise ValueError("ANN pilot requires the published Two-Tower selection evidence.")
    if (
        profile.get("complete") is not True
        or profile.get("decision") != "proceed to ANN compatibility pilot"
        or profile.get("completed_folds") != [1, 2, 3, 4]
        or profile.get("input_sha256") != manifest["source_sha256"]
        or profile.get("manifest_sha256") != manifest_fingerprint(manifest)
    ):
        raise ValueError("ANN pilot requires the complete exact-cost profile.")
    runtime = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "torch": torch.__version__,
        "faiss": faiss.__version__,
    }
    if {key: value for key, value in runtime.items() if key != "faiss"} != lock["runtime"]:
        raise ValueError("ANN pilot runtime differs from the locked Two-Tower runtime.")
    identity = {
        "protocol_version": POLICY["protocol"],
        "phase": "development-fold-1-pilot",
        "blind_holdout": False,
        "policy": POLICY,
        "policy_sha256": _sha(POLICY),
        "runner_sha256": _runner_sha256(root),
        "manifest_sha256": manifest_fingerprint(manifest),
        "input_sha256": manifest["source_sha256"],
        "m8_lock_sha256": sha256_file(args.two_tower_lock),
        "m8_development_sha256": sha256_file(args.two_tower_development),
        "profile_sha256": sha256_file(args.profile),
        "runtime": runtime,
    }
    artifact = {**identity, "results": [], "complete": False, "decision": "pending"}
    if args.output.exists():
        artifact = json.loads(args.output.read_text(encoding="utf-8"))
        _validate_checkpoint(artifact, identity)
    if artifact["complete"]:
        print(
            json.dumps({"decision": artifact["decision"], "comparisons": len(artifact["results"])})
        )
        return
    fold = manifest["folds"][0]
    interactions = pd.read_parquet(args.input_path)
    if interactions[["user_id", "item_id", "timestamp"]].isna().any().any():
        raise ValueError("ANN feasibility interactions contain null IDs or timestamps.")
    train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]].copy()
    train["user_id"] = train["user_id"].astype(str)
    train["item_id"] = train["item_id"].astype(str)
    train = train.sort_values(["timestamp", "user_id", "item_id"], kind="mergesort")
    fold_path = args.fold_dir / "fold_01"
    targets = pd.read_parquet(fold_path / "warm_targets.parquet")
    catalog = pd.read_parquet(fold_path / "items_train.parquet")
    validate_targets(train, targets, "warm")
    ids = set(targets["user_id"].astype(str))
    history_rows = train.loc[train["user_id"].isin(ids)]
    histories = {
        user: tuple(group["item_id"]) for user, group in history_rows.groupby("user_id", sort=False)
    }
    selected = _sample_indices(targets, histories, seed=43, size=POLICY["sample_size"])
    contexts = [
        RetrievalContext(
            str(targets.iloc[i]["user_id"]), histories[str(targets.iloc[i]["user_id"])]
        )
        for i in selected
    ]
    selected_targets = [str(targets.iloc[i]["item_id"]) for i in selected]
    sample_sha256 = _sha(
        [(str(targets.iloc[i]["user_id"]), str(targets.iloc[i]["item_id"])) for i in selected]
    )
    if sample_sha256 != profile["results"][0]["sample_sha256"]:
        raise ValueError("ANN pilot sample differs from the exact-cost profile sample.")
    print("ANN fold-1 pilot: fitting selected Two-Tower", flush=True)
    exact = TwoTowerRetriever(catalog).fit(train, **POLICY["model_config"], **POLICY["training"])
    if exact.item_vectors is None:
        raise ValueError("ANN feasibility could not fit the selected Two-Tower model.")
    vector_sha256 = hashlib.sha256(exact.item_vectors.tobytes()).hexdigest()
    for config in CONFIGS[len(artifact["results"]) :]:
        print(f"ANN pilot config {config}: building index", flush=True)
        ann = FaissTwoTowerANN(exact, **config)
        measured = _measure_pair(exact, ann, contexts, selected_targets)
        artifact["results"].append(
            {
                "fold_index": 1,
                "config": config,
                "sample_sha256": sample_sha256,
                "item_vector_sha256": vector_sha256,
                "catalog_items": len(exact.catalog),
                "model_fit_seconds": exact.fit_seconds,
                "index_build_seconds": ann.build_seconds,
                "serialized_index_bytes": ann.serialized_index_bytes,
                "index_search_calls": ann.search_calls,
                "max_effective_ef_search": ann.max_effective_ef_search,
                "timing_scope": "paired warm direct-source generate(context, limit=1000) after warmup",
                **measured,
            }
        )
        artifact["complete"] = len(artifact["results"]) == len(CONFIGS)
        if artifact["complete"]:
            artifact["decision"] = (
                "no-go: all configs fail fold-1 paired p95 gate"
                if all(not row["passes_speed_gate"] for row in artifact["results"])
                else "continue complete development evaluation"
            )
        _save(args.output, artifact)
        print(
            f"  exact p95={measured['exact_latency']['latency_p95_ms']:.3f} ms; "
            f"ANN p95={measured['ann_latency']['latency_p95_ms']:.3f} ms; "
            f"pass={measured['passes_speed_gate']}",
            flush=True,
        )
    print(json.dumps({"decision": artifact["decision"], "comparisons": len(artifact["results"])}))


if __name__ == "__main__":
    main()
