"""Evaluate global and recent popularity fallbacks for first-time users."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.recommendation.recent_popularity import RecentPopularityRecommender


def _metrics(targets: pd.Series, ranking: list[str]) -> dict[str, float]:
    if targets.empty:
        return {f"{name}@{k}": 0.0 for k in (5, 10, 20) for name in ("HR", "MRR", "NDCG")}
    ranks = targets.astype(str).map({item: rank for rank, item in enumerate(ranking, start=1)})
    metrics = {}
    for k in (5, 10, 20):
        hits = ranks.le(k).fillna(False).to_numpy()
        hit_ranks = ranks[hits].to_numpy(dtype=float)
        metrics[f"HR@{k}"] = round(float(hits.mean()), 6)
        metrics[f"MRR@{k}"] = round(float((1.0 / hit_ranks).sum() / len(ranks)), 6)
        metrics[f"NDCG@{k}"] = round(float((1.0 / np.log2(hit_ranks + 1)).sum() / len(ranks)), 6)
    return metrics


def _summarize(rows: list[dict]) -> dict:
    summary = {}
    for name in ("global_popularity", "recent_popularity"):
        model_rows = [row for row in rows if row["model"] == name]
        total = sum(row["evaluation_users"] for row in model_rows)
        if not model_rows:
            continue
        summary[name] = {
            "users": total,
            "pooled_metrics": {
                key: round(
                    sum(row["evaluation_users"] * row["metrics"][key] for row in model_rows)
                    / total,
                    6,
                )
                if total
                else 0.0
                for key in model_rows[0]["metrics"]
            },
        }
    return summary


def _save(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    pending.replace(path)


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/rolling/cold.json"))
    parser.add_argument(
        "--max-fold", type=int, default=9, help="Use 4 for early cold checks before sweeps finish."
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
        raise ValueError("Input interactions do not match manifest.")
    verify_fold_files(manifest, args.fold_dir, args.max_fold)
    interactions = pd.read_parquet(args.input_path)
    if args.output.exists():
        artifact = json.loads(args.output.read_text(encoding="utf-8"))
        if (
            artifact.get("protocol_version") != manifest["protocol_version"]
            or artifact.get("source_sha256") != manifest["source_sha256"]
            or artifact.get("manifest_sha256") != fingerprint
        ):
            raise ValueError("Existing cold results belong to another dataset or protocol.")
    else:
        artifact = {
            "protocol_version": manifest["protocol_version"],
            "source_sha256": manifest["source_sha256"],
            "manifest_sha256": fingerprint,
            "blind_holdout": False,
            "role": "cold-start diagnostic; folds 5-9 outcomes were previously viewed",
            "cohort": "first event of users absent from the fold training snapshot",
            "results": [],
            "known_item_rate_by_fold": [],
        }
    artifact["blind_holdout"] = False
    artifact["numeric_threads"] = 1
    artifact["role"] = (
        "cold-start selection-fold diagnostic"
        if args.max_fold <= 4
        else "cold-start diagnostic; folds 5-9 outcomes were previously viewed"
    )
    rows = artifact["results"]
    done = {(row["model"], row["fold_index"]) for row in rows}
    expected_users = {fold["fold_index"]: fold["cold_target_users"] for fold in manifest["folds"]}
    if len(done) != len(rows) or any(
        row["model"] not in ("global_popularity", "recent_popularity")
        or row["fold_index"] not in expected_users
        or row["evaluation_users"] != expected_users[row["fold_index"]]
        or row["fold_index"] > args.max_fold
        for row in rows
    ):
        raise ValueError("Existing cold results contain duplicate or later-fold rows.")
    known_rates = {
        row["fold_index"]: row["rate"] for row in artifact.get("known_item_rate_by_fold", [])
    }
    for fold in manifest["folds"][: args.max_fold]:
        index = fold["fold_index"]
        missing = [
            name for name in ("global_popularity", "recent_popularity") if (name, index) not in done
        ]
        if not missing and index in known_rates:
            continue
        train = interactions.loc[interactions["timestamp"] <= fold["train_cutoff"]]
        path = args.fold_dir / f"fold_{index:02d}"
        targets = pd.read_parquet(path / "cold_targets.parquet")
        catalog = pd.read_parquet(path / "items_train.parquet", columns=["item_id"])
        if len(targets) != fold["cold_target_users"]:
            raise ValueError(f"Cold targets for fold {index} do not match manifest.")
        known = targets["item_id"].astype(str).isin(set(catalog["item_id"].astype(str)))
        known_rates[index] = round(float(known.mean()), 6) if len(targets) else None
        for name in missing:
            model = (
                PopularityRecommender()
                if name == "global_popularity"
                else RecentPopularityRecommender(window_days=30)
            )
            if targets.empty:
                metrics = _metrics(targets["item_id"], [])
            else:
                if isinstance(model, RecentPopularityRecommender):
                    model.fit(train, cutoff=fold["train_cutoff"])
                else:
                    model.fit(train)
                metrics = _metrics(targets["item_id"], model.recommend(20))
            rows.append(
                {
                    "fold_index": index,
                    "model": name,
                    "evaluation_users": len(targets),
                    "metrics": metrics,
                }
            )
            artifact["summary"] = _summarize(rows)
            artifact["known_item_rate_by_fold"] = [
                {"fold_index": fold_index, "rate": rate}
                for fold_index, rate in sorted(known_rates.items())
            ]
            _save(args.output, artifact)
            print(f"fold {index} {name}: HR@20={metrics['HR@20']:.6f}", flush=True)
        artifact["known_item_rate_by_fold"] = [
            {"fold_index": fold_index, "rate": rate}
            for fold_index, rate in sorted(known_rates.items())
        ]
        _save(args.output, artifact)
    artifact["summary"] = _summarize(rows)
    _save(args.output, artifact)
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
