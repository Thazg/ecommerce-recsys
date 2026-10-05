"""Prepare shared, causal evaluation windows for every M4–M6 recommender."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.data.catalog import build_train_catalog
from ecommerce_recsys.data.rolling_provenance import fold_hashes, property_hashes, sha256_file
from ecommerce_recsys.data.splitting import (
    rolling_temporal_cutoffs,
    rolling_temporal_fold,
)

PROTOCOL_VERSION = "rolling-temporal"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare rolling temporal evaluation folds.")
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument(
        "--manifest-output", type=Path, default=Path("benchmarks/rolling/manifest.json")
    )
    parser.add_argument("--n-windows", type=int, default=10)
    parser.add_argument("--min-train-interactions", type=int, default=1)
    args = parser.parse_args()
    if args.n_windows != 10 or args.min_train_interactions != 1:
        raise ValueError("The rolling-temporal benchmark requires 10 windows and one prior event.")

    interactions = pd.read_parquet(args.input_path)
    cutoffs = rolling_temporal_cutoffs(interactions, args.n_windows)
    source_sha256 = sha256_file(args.input_path)
    raw_property_sha256 = property_hashes(args.raw_dir)
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "source": args.input_path.name,
        "source_sha256": source_sha256,
        "raw_property_sha256": raw_property_sha256,
        "n_windows": args.n_windows,
        "min_train_interactions": args.min_train_interactions,
        "target_rule": "first item in window unseen in that user's training history",
        "cold_target_rule": "first event in window for a user absent from training",
        "folds": [],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    if args.manifest_output.exists():
        manifest = json.loads(args.manifest_output.read_text(encoding="utf-8"))
        if any(manifest.get(key) != value for key, value in expected.items() if key != "folds"):
            raise ValueError(
                "Existing rolling manifest has different inputs or settings. "
                "Use a fresh output directory and manifest path."
            )
        if len(manifest.get("folds", [])) > args.n_windows - 1:
            raise ValueError("Existing rolling manifest has too many folds.")
    else:
        manifest = expected
    for fold_index in range(1, args.n_windows):
        fold_dir = args.output_dir / f"fold_{fold_index:02d}"
        if fold_index <= len(manifest["folds"]):
            saved = manifest["folds"][fold_index - 1]
            if (
                saved["fold_index"] != fold_index
                or saved["train_cutoff"] != cutoffs[fold_index - 1]
                or saved["evaluation_cutoff"] != cutoffs[fold_index]
                or fold_hashes(fold_dir) != saved.get("files_sha256")
            ):
                raise ValueError(f"Existing fold {fold_index} differs from its manifest.")
            print(f"Fold {fold_index}: verified, skipping", flush=True)
            continue
        print(f"Preparing rolling fold {fold_index}/{args.n_windows - 1}...", flush=True)
        train, warm_targets, cold_targets, window = rolling_temporal_fold(
            interactions,
            cutoffs,
            fold_index,
            min_train_interactions=args.min_train_interactions,
        )
        if warm_targets.empty:
            raise ValueError(f"Fold {fold_index} has no warm-user targets.")
        catalog = build_train_catalog(train, args.raw_dir)
        fold_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in (
            ("warm_targets.parquet", warm_targets),
            ("cold_targets.parquet", cold_targets),
            ("items_train.parquet", catalog),
        ):
            path = fold_dir / name
            pending = path.with_suffix(".parquet.tmp")
            frame.to_parquet(pending, index=False, engine="pyarrow")
            pending.replace(path)

        known_items = set(catalog["item_id"].astype(str))
        fold = {
            "fold_index": fold_index,
            "train_cutoff": cutoffs[fold_index - 1],
            "evaluation_cutoff": cutoffs[fold_index],
            "training_interactions": len(train),
            "training_users": train["user_id"].nunique(),
            "evaluation_window_interactions": len(window),
            "evaluation_window_users": window["user_id"].nunique(),
            "warm_target_users": len(warm_targets),
            "cold_target_users": len(cold_targets),
            "train_catalog_items": len(catalog),
            "warm_target_new_item_rate": round(
                (~warm_targets["item_id"].astype(str).isin(known_items)).mean(), 6
            ),
            "files_sha256": fold_hashes(fold_dir),
        }
        manifest["folds"].append(fold)
        pending_manifest = args.manifest_output.with_suffix(".json.tmp")
        pending_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        pending_manifest.replace(args.manifest_output)
        print(
            f"  warm={len(warm_targets):,}, cold={len(cold_targets):,}, catalog={len(catalog):,}",
            flush=True,
        )

    print(f"Wrote {args.manifest_output}")


if __name__ == "__main__":
    main()
