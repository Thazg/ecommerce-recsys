"""Build a locked offline policy snapshot and reconcile loaded fold quality."""

from __future__ import annotations

import argparse
import gc
import json
import math
from collections import Counter
from dataclasses import fields
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.contract import digest, file_sha, runtime_code, write_json
from ecommerce_recsys.artifacts.export import export_bundle, recover_sealed_bundle
from ecommerce_recsys.artifacts.runtime import array_digest, evidence_digest
from ecommerce_recsys.evaluation.model_policy import PolicyTotals, validate_result
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import SnapshotFeatures, request_id
from ecommerce_recsys.retrieval.base import RetrievalContext

if __package__:
    from scripts import verify_model_policy as upstream
    from scripts.verify_model_artifacts import verify_references
else:
    import verify_model_policy as upstream
    from verify_model_artifacts import verify_references


def producer_sha() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = (
        Path(__file__),
        root / "scripts/verify_model_artifacts.py",
        root / "src/ecommerce_recsys/artifacts/export.py",
    )
    return digest({p.name: upstream.normalized_sha256(p) for p in paths})


def producer_reference(predictor, context) -> dict:
    warm = context.user_id is not None
    generator = predictor.generators["hybrid"] if warm else predictor.sources["recent_popularity"]
    pool = generator.generate(context, 1000)
    rows = predictor.feature_rows(pool, context) if warm else []
    matrix = (
        upstream.runner.ranker.feature_matrix(pd.DataFrame(rows)) if rows else np.empty((0, 32))
    )
    scores = predictor.model.score(matrix)
    ids = [candidate.item_id for candidate in pool]
    order = np.lexsort((np.array(ids), -scores)) if warm else np.arange(len(ids))
    return {
        "user_id": context.user_id,
        "trace": {
            "pool": ids,
            "output": [ids[i] for i in order[:20]],
            "evidence_sha256": evidence_digest(pool),
            "features_sha256": array_digest(matrix),
            "scores_sha256": array_digest(scores),
            "route": "hybrid_learned" if warm else "recent_popularity",
        },
    }


def reconcile(actual: dict, expected: dict) -> None:
    if set(actual) != set(expected):
        raise ValueError("Loaded quality metric schema differs from published policy.")
    for name, value in expected.items():
        if isinstance(value, dict):
            reconcile(actual[name], value)
        elif isinstance(value, float):
            if not math.isclose(actual[name], value, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"Loaded fold metric differs: {name}")
        elif actual[name] != value:
            raise ValueError(f"Loaded fold count differs: {name}")


def totals_state(totals) -> dict:
    state = {
        field.name: sorted(totals.unique) if field.name == "unique" else getattr(totals, field.name)
        for field in fields(totals)
        if field.name not in {"catalog", "categories"}
    }
    for name in ("hits", "reciprocal", "discounted"):
        state[name] = {str(key): value for key, value in state[name].items()}
    return state


def loaded_quality(bundle, targets, expected, checkpoint: Path, identity: dict) -> dict:
    categories = {item: bundle.features.categories.get(item) for item in bundle.items}
    warm = PolicyTotals(frozenset(bundle.items), categories)
    completed_seconds = 0.0
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (
            saved["identity"] != identity
            or saved["payload_sha256"] != digest(saved["state"])
            or set(saved["state"]) != set(totals_state(warm))
            or not 0 <= saved["state"]["requests"] <= len(targets["warm"])
        ):
            raise ValueError("Loaded quality checkpoint differs from bundle/targets/code.")
        for name, value in saved["state"].items():
            if name == "unique":
                value = set(value)
            elif name in {"hits", "reciprocal", "discounted"}:
                value = {int(k): v for k, v in value.items()}
            setattr(warm, name, value)
        validate_result(warm.output(), requests=warm.requests, catalog_size=len(bundle.items))
        if not warm.unique.issubset(bundle.items):
            raise ValueError("Quality checkpoint contains unknown recommended items.")
        completed_seconds = saved["quality_seconds"]
    started = perf_counter()
    for position, target in enumerate(targets["warm"].itertuples(index=False), 1):
        if position <= warm.requests:
            continue
        user = str(target.user_id)
        if user not in bundle.user_index:
            raise ValueError("Warm target user absent from bundle.")
        trace = bundle.trace(user)
        warm.add(
            trace["pool"],
            trace["output"],
            str(target.item_id),
            frozenset(bundle.context(user).history),
        )
        if position % 500 == 0 or position == len(targets["warm"]):
            state = totals_state(warm)
            write_json(
                checkpoint,
                {
                    "identity": identity,
                    "state": state,
                    "payload_sha256": digest(state),
                    "quality_seconds": completed_seconds + perf_counter() - started,
                },
            )
            print(f"Loaded bundle: {position:,}/{len(targets['warm']):,} warm requests", flush=True)
    cold = PolicyTotals(warm.catalog, categories)
    trace = bundle.trace(None)
    cold.add_shared(trace["pool"], trace["output"], Counter(targets["cold"]["item_id"].astype(str)))
    result = {"warm": warm.output(), "cold": cold.output()}
    for cohort in result:
        validate_result(
            result[cohort], requests=len(targets[cohort]), catalog_size=len(bundle.items)
        )
        reconcile(
            result[cohort],
            expected[cohort]["hybrid_learned" if cohort == "warm" else "recent_popularity"],
        )
    return {"quality": result, "quality_seconds": completed_seconds + perf_counter() - started}


def fit_export(args, fold, configs, model, provenance):
    interactions = pd.read_parquet(args.data_dir / "processed/interactions.parquet")
    train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]].copy()
    del interactions
    folder = args.data_dir / "rolling" / f"fold_{args.fold:02d}"
    catalog = pd.read_parquet(folder / "items_train.parquet")
    if (
        len(train) != fold["training_interactions"]
        or train["user_id"].nunique() != fold["training_users"]
        or len(catalog) != fold["train_catalog_items"]
        or catalog["item_id"].astype(str).duplicated().any()
        or set(train["item_id"].astype(str)) != set(catalog["item_id"].astype(str))
    ):
        raise ValueError("Build snapshot differs from manifest counts or catalog.")
    features = SnapshotFeatures.from_frames(train, catalog, int(fold["train_cutoff"]))
    print(f"Fitting locked sources at fold {args.fold} cutoff (one numerical thread)", flush=True)
    sources, hybrids, fit_seconds, factor_bytes = upstream.runner.ranker.build_sources(
        train, catalog, fold["train_cutoff"], configs
    )
    predictor = upstream.runner.OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=features,
        model=model,
        fold_index=args.fold,
        categories={
            str(row.item_id): features.categories.get(str(row.item_id))
            for row in catalog.itertuples(index=False)
        },
    )
    # Reference selection is deterministic and independent of evaluation labels.
    users = sorted(features.user_events, key=lambda user: request_id(args.fold, user))[:100]
    rows = train.loc[train["user_id"].astype(str).isin(users)]
    contexts = {
        str(user): RetrievalContext(str(user), tuple(frame["item_id"].astype(str)))
        for user, frame in rows.groupby("user_id", sort=False)
    }
    references = [producer_reference(predictor, contexts[user]) for user in users]
    references.append(producer_reference(predictor, RetrievalContext()))
    snapshot = {
        "fold_index": args.fold,
        "cutoff": int(fold["train_cutoff"]),
        "ranker_label_cutoff": provenance["ranker_label_cutoff"],
        "users": fold["training_users"],
        "items": len(catalog),
        "events": len(train),
        "configs": configs,
        "seeds": {"als_fit": 42, "ranker_negative_sampling": 42},
    }
    started = perf_counter()
    path = export_bundle(
        args.artifact_dir,
        args.version,
        sources=sources,
        features=features,
        weights=model.weights,
        scales=model.scales,
        snapshot=snapshot,
        provenance=provenance,
        references=references,
    )
    cost = {
        "source_fit_seconds": fit_seconds,
        "als_factor_array_bytes": factor_bytes,
        "export_seconds": perf_counter() - started,
    }
    write_json(
        args.receipt.with_suffix(".build-cost.json"),
        {
            "manifest_sha256": file_sha(path / "model_manifest.json"),
            "cost": cost,
        },
    )
    return path


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--benchmark-dir", type=Path, default=Path("benchmarks"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--version")
    parser.add_argument("--fold", type=int, choices=range(5, 10), default=9)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    args.version = args.version or f"retailrocket-fold{args.fold:02d}-v1"
    args.receipt = args.receipt or args.benchmark_dir / f"artifacts/fold{args.fold:02d}_v1.json"
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    supplement = upstream.build_provenance(args.data_dir, args.benchmark_dir)
    supplement_path = args.benchmark_dir / "model_policy/provenance_v1.json"
    if json.loads(supplement_path.read_text(encoding="utf-8")) != supplement:
        raise ValueError("Published policy provenance supplement differs.")
    bound = upstream.runner_args(args.data_dir, args.benchmark_dir)
    manifest, configs, _, _, _, ranker_identity, _, _ = upstream.runner.inputs(bound, 9)
    fold = manifest["folds"][args.fold - 1]
    model, _ = upstream.runner.diversity.locked_ranker_model(
        upstream.runner.upstream_args(bound), ranker_identity
    )
    provenance = {
        "producer_sha256": producer_sha(),
        "runtime_code_sha256": runtime_code(),
        "policy_provenance_sha256": file_sha(supplement_path),
        "policy_lock_sha256": file_sha(bound.selection_lock),
        "rolling_manifest_sha256": file_sha(bound.manifest),
        "interactions_sha256": manifest["source_sha256"],
        "catalog_sha256": fold["files_sha256"]["items_train.parquet"],
        "ranker_diagnostic_sha256": file_sha(bound.ranker_diagnostic),
        "ranker_model_sha256": upstream.runner.digest(upstream.runner.model_record(model)),
        "ranker_label_cutoff": manifest["folds"][3]["evaluation_cutoff"],
        "snapshot_fold": args.fold,
    }
    if args.receipt.exists():
        prior = json.loads(args.receipt.read_text(encoding="utf-8"))
        if (
            prior.get("bundle_version") != args.version
            or prior.get("provenance") != provenance
            or prior.get("fold_index") != args.fold
        ):
            raise ValueError("Receipt path belongs to a different build; choose a distinct path.")
    path = recover_sealed_bundle(args.artifact_dir, args.version, provenance)
    if path is None:
        path = fit_export(args, fold, configs, model, provenance)
        gc.collect()
    started = perf_counter()
    bundle = load_bundle(path)
    load_seconds = perf_counter() - started
    count = verify_references(bundle, path)
    print(f"Verified {count} exact producer/loaded traces; load {load_seconds:.2f}s", flush=True)
    folder = args.data_dir / "rolling" / f"fold_{args.fold:02d}"
    targets = {
        cohort: pd.read_parquet(folder / f"{cohort}_targets.parquet") for cohort in ("warm", "cold")
    }
    for cohort, frame in targets.items():
        if (
            len(frame) != fold[f"{cohort}_target_users"]
            or frame["user_id"].duplicated().any()
            or not (
                (frame["timestamp"] > fold["train_cutoff"])
                & (frame["timestamp"] <= fold["evaluation_cutoff"])
            ).all()
        ):
            raise ValueError("Evaluation target count, identity or time boundary differs.")
    reference = json.loads(bound.diagnostic_artifact.read_text(encoding="utf-8"))
    expected = next(row for row in reference["folds"] if row["fold_index"] == args.fold)
    identity = {
        "manifest_sha256": file_sha(path / "model_manifest.json"),
        "producer_sha256": producer_sha(),
        "target_sha256": {
            cohort: file_sha(folder / f"{cohort}_targets.parquet") for cohort in targets
        },
    }
    quality = loaded_quality(
        bundle, targets, expected, args.receipt.with_suffix(".checkpoint.json"), identity
    )
    cost_path = args.receipt.with_suffix(".build-cost.json")
    build_cost = None
    if cost_path.exists():
        cost_record = json.loads(cost_path.read_text(encoding="utf-8"))
        if cost_record.get("manifest_sha256") != identity["manifest_sha256"]:
            raise ValueError("Build cost belongs to a different bundle.")
        build_cost = cost_record["cost"]
    receipt = {
        "artifact": "offline-model-bundle-validation-v1",
        "complete": True,
        "bundle_version": args.version,
        "fold_index": args.fold,
        "identity": identity,
        "runtime": bundle.manifest["runtime"],
        "runtime_code_sha256": runtime_code(),
        "snapshot": bundle.manifest["snapshot"],
        "provenance": provenance,
        "components": bundle.manifest["components"],
        "component_bytes": sum(row["bytes"] for row in bundle.manifest["components"].values()),
        "exact_reference_requests": count,
        "loaded_quality_matches_policy": True,
        "blind_holdout": False,
        "load_seconds": load_seconds,
        "build_cost": build_cost,
        **quality,
    }
    receipt["payload_sha256"] = digest(receipt)
    if args.receipt.exists():
        previous = json.loads(args.receipt.read_text())
        for key in ("identity", "quality", "components", "provenance"):
            if previous[key] != receipt[key]:
                raise ValueError("Existing validation receipt differs; use a new receipt path.")
        print(f"Verified existing receipt: {args.receipt}", flush=True)
    else:
        write_json(args.receipt, receipt)
        print(f"Completed loaded-bundle quality reconciliation: {args.receipt}", flush=True)


if __name__ == "__main__":
    main()
