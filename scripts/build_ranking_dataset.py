"""Generate causal warm ranking rows for rolling development folds 1–4."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter

import implicit
import numpy as np
import pandas as pd
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.candidates import validate_targets
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from ecommerce_recsys.ranking.dataset import (
    ABSENT_SOURCE_RANK,
    CANDIDATE_BUDGET,
    EVENT_TYPES,
    SOURCE_NAMES,
    SnapshotFeatures,
    audit_rows,
    request_id,
    request_row,
)
from ecommerce_recsys.retrieval.base import RetrievalContext

if __package__:
    from scripts.benchmark_candidates import POLICY as M7_POLICY
    from scripts.benchmark_candidates import build_sources
else:
    from benchmark_candidates import POLICY as M7_POLICY
    from benchmark_candidates import build_sources

POLICY = {
    "version": 1,
    "cohort": "warm",
    "folds": [1, 2, 3, 4],
    "generator": "hybrid",
    "candidate_budget": CANDIDATE_BUDGET,
    "label": "first unseen future item equals returned candidate item",
    "source_rank_absent": ABSENT_SOURCE_RANK,
    "source_score_absent": 0.0,
    "numeric_threads": 1,
}


def implementation_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "src/ecommerce_recsys").rglob("*.py")),
        root / "scripts/benchmark_candidates.py",
        root / "scripts/build_ranking_dataset.py",
        root / "scripts/prepare_rolling_data.py",
        root / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def candidate_schema() -> pa.Schema:
    fields = [
        pa.field("request_id", pa.string()),
        pa.field("fold_index", pa.int8()),
        pa.field("item_id", pa.string()),
        pa.field("retrieval_rank", pa.int16()),
        pa.field("label", pa.int8()),
        pa.field("rrf_score", pa.float64()),
        pa.field("source_count", pa.int8()),
        pa.field("user_event_count", pa.int32()),
        pa.field("user_distinct_item_count", pa.int32()),
        pa.field("user_days_since_last_event", pa.float64()),
        pa.field("item_event_count", pa.int32()),
        pa.field("item_distinct_user_count", pa.int32()),
        pa.field("item_days_since_last_event", pa.float64()),
        pa.field("category_known", pa.int8()),
        pa.field("user_category_event_count", pa.int32()),
    ]
    for event_type in EVENT_TYPES:
        fields.extend(
            (
                pa.field(f"user_{event_type}_count", pa.int32()),
                pa.field(f"item_{event_type}_count", pa.int32()),
            )
        )
    for source in SOURCE_NAMES:
        fields.extend(
            (
                pa.field(f"{source}_present", pa.int8()),
                pa.field(f"{source}_rank", pa.int16()),
                pa.field(f"{source}_score", pa.float64()),
            )
        )
    return pa.schema(fields)


REQUEST_SCHEMA = pa.schema(
    [
        pa.field("request_id", pa.string()),
        pa.field("fold_index", pa.int8()),
        pa.field("user_id", pa.string()),
        pa.field("cutoff", pa.int64()),
        pa.field("target_item_id", pa.string()),
        pa.field("target_timestamp", pa.int64()),
        pa.field("target_in_catalog", pa.int8()),
        pa.field("target_in_pool", pa.int8()),
        pa.field("pool_size", pa.int16()),
    ]
)


def payload_fingerprint(artifact: dict) -> str:
    return hashlib.sha256(
        json.dumps(artifact.get("folds", []), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def data_fingerprint(artifact: dict) -> str:
    """Identify persisted fold data independently of run timing and sampled RSS."""
    rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"fit_seconds", "build_seconds", "peak_rss_bytes"}
        }
        for row in artifact.get("folds", [])
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest()


def save_checkpoint(path: Path, artifact: dict) -> None:
    artifact["payload_sha256"] = payload_fingerprint(artifact)
    artifact["data_sha256"] = data_fingerprint(artifact)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def validate_checkpoint(artifact: dict, expected: dict, output_dir: Path) -> None:
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise ValueError("Ranking dataset checkpoint provenance or policy changed.")
    if artifact.get("payload_sha256") != payload_fingerprint(artifact):
        raise ValueError("Ranking dataset checkpoint rows changed.")
    if artifact.get("data_sha256") != data_fingerprint(artifact):
        raise ValueError("Ranking dataset checkpoint data identity changed.")
    indices = [row["fold_index"] for row in artifact.get("folds", [])]
    if indices != list(range(1, len(indices) + 1)) or len(indices) > 4:
        raise ValueError(
            "Ranking dataset checkpoint contains incomplete or invalid development folds."
        )
    for row in artifact["folds"]:
        fold_dir = output_dir / f"fold_{row['fold_index']:02d}"
        for name in ("requests", "candidates"):
            if sha256_file(fold_dir / f"{name}.parquet") != row[f"{name}_sha256"]:
                raise ValueError(f"Ranking dataset {name} file does not match its checkpoint hash.")
        if not (
            row["positives"] <= row["reachable"] <= row["requests"]
            and row["candidates"] <= CANDIDATE_BUDGET * row["requests"]
            and row["empty"] <= row["requests"]
        ):
            raise ValueError("Ranking dataset checkpoint counts are invalid.")


def write_fold(
    *,
    index: int,
    cutoff: int,
    evaluation_cutoff: int,
    train: pd.DataFrame,
    catalog: pd.DataFrame,
    targets: pd.DataFrame,
    configs: dict,
    output_dir: Path,
    batch_size: int,
    reference_row: dict,
) -> dict:
    if batch_size <= 0:
        raise ValueError("Batch size must be positive.")
    if any(type(value) is not int for value in (index, cutoff, evaluation_cutoff)):
        raise ValueError("Fold index and cutoff timestamps must be plain integers.")
    validate_targets(train, targets, "warm")
    if not pd.api.types.is_integer_dtype(targets["timestamp"]):
        raise ValueError("Ranking dataset target timestamps must be integer milliseconds.")
    if (train["timestamp"] > cutoff).any() or (
        not targets.empty
        and not (
            (targets["timestamp"] > cutoff) & (targets["timestamp"] <= evaluation_cutoff)
        ).all()
    ):
        raise ValueError("Ranking dataset training or targets cross the declared cutoff.")
    if catalog["item_id"].isna().any() or catalog["item_id"].astype(str).duplicated().any():
        raise ValueError("Ranking dataset catalog contains null or duplicate item IDs.")
    catalog_ids = frozenset(catalog["item_id"].astype(str))
    if set(train["item_id"].astype(str)) != catalog_ids:
        raise ValueError("Ranking dataset catalog differs from train-time interactions.")
    started = perf_counter()
    sources, hybrids, fit_seconds, _ = build_sources(train, catalog, cutoff, configs)
    hybrid = next((generator for generator in hybrids if generator.name == "hybrid"), None)
    if hybrid is None:
        raise ValueError("Ranking dataset requires the hybrid candidate generator.")
    features = SnapshotFeatures.from_frames(train, catalog, cutoff)
    ids = set(targets["user_id"].astype(str))
    history_rows = train.loc[train["user_id"].astype(str).isin(ids)].copy()
    history_rows["user_id"] = history_rows["user_id"].astype(str)
    histories = {
        user: tuple(group["item_id"].astype(str))
        for user, group in history_rows.groupby("user_id", sort=False)
    }
    fold_dir = output_dir / f"fold_{index:02d}"
    fold_dir.mkdir(parents=True, exist_ok=True)
    candidate_tmp = fold_dir / "candidates.parquet.tmp"
    request_tmp = fold_dir / "requests.parquet.tmp"
    request_rows: list[dict] = []
    batch_requests: list[dict] = []
    batch_candidates: list[dict] = []
    totals = {key: 0 for key in ("requests", "candidates", "positives", "reachable", "empty")}
    peak_rss = psutil.Process().memory_info().rss
    schema = candidate_schema()
    with pq.ParquetWriter(candidate_tmp, schema, compression="zstd") as writer:
        for position, target in enumerate(targets.itertuples(index=False), start=1):
            user = str(target.user_id)
            target_item = str(target.item_id)
            context = RetrievalContext(user, histories[user])
            seen_items = frozenset(context.history)
            key = request_id(index, user)
            pool = hybrid.generate(context, CANDIDATE_BUDGET)
            if any(
                candidate.item_id in seen_items or candidate.item_id not in catalog_ids
                for candidate in pool
            ):
                raise ValueError("Ranking dataset pool contains seen or catalog-ineligible items.")
            req = request_row(
                fold_index=index,
                cutoff=cutoff,
                evaluation_cutoff=evaluation_cutoff,
                user_id=user,
                target_item_id=target_item,
                target_timestamp=int(target.timestamp),
                catalog=catalog_ids,
                candidates=pool,
                request_key=key,
            )
            request_rows.append(req)
            batch_requests.append(req)
            batch_candidates.extend(
                features.candidate_row(
                    fold_index=index,
                    context=context,
                    candidate=candidate,
                    rank=rank,
                    target_item_id=target_item,
                    request_key=key,
                    seen_items=seen_items,
                )
                for rank, candidate in enumerate(pool, start=1)
            )
            if position % batch_size == 0 or position == len(targets):
                counts = audit_rows(batch_requests, batch_candidates)
                for key, value in counts.items():
                    totals[key] += value
                if batch_candidates:
                    writer.write_table(pa.Table.from_pylist(batch_candidates, schema=schema))
                batch_requests.clear()
                batch_candidates.clear()
                peak_rss = max(peak_rss, psutil.Process().memory_info().rss)
                if position % 500 == 0 or position == len(targets):
                    print(f"  fold {index}: {position:,}/{len(targets):,} requests", flush=True)
    pq.write_table(
        pa.Table.from_pylist(request_rows, schema=REQUEST_SCHEMA), request_tmp, compression="zstd"
    )
    if totals["requests"] != len(targets):
        raise ValueError("Ranking dataset request count differs from target count.")
    reference_totals = reference_row["totals"]["1000"]
    if (
        totals["positives"] != reference_totals["hits"]
        or totals["candidates"] != reference_totals["candidate_count"]
        or totals["empty"] != reference_totals["empty_requests"]
    ):
        raise ValueError("Fresh ranking pools do not reproduce the M7 fold counts.")
    candidate_tmp.replace(fold_dir / "candidates.parquet")
    request_tmp.replace(fold_dir / "requests.parquet")
    return {
        "fold_index": index,
        "cutoff": cutoff,
        **totals,
        "reachable_but_unretrieved": totals["reachable"] - totals["positives"],
        "unreachable": totals["requests"] - totals["reachable"],
        "candidate_recall@1000": totals["positives"] / totals["requests"],
        "fit_seconds": fit_seconds,
        "build_seconds": perf_counter() - started,
        "peak_rss_bytes": peak_rss,
        "requests_sha256": sha256_file(fold_dir / "requests.parquet"),
        "candidates_sha256": sha256_file(fold_dir / "candidates.parquet"),
        "requests_bytes": (fold_dir / "requests.parquet").stat().st_size,
        "candidates_bytes": (fold_dir / "candidates.parquet").stat().st_size,
    }


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--sweep-dir", type=Path, default=Path("benchmarks/rolling"))
    parser.add_argument(
        "--reference", type=Path, default=Path("benchmarks/retrieval/candidates.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/ranking/m10_v1"))
    parser.add_argument(
        "--artifact", type=Path, default=Path("benchmarks/ranking/m10_quality_v1.json")
    )
    parser.add_argument("--max-fold", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.max_fold <= 4:
        raise ValueError(
            "Ranking dataset is development-only; folds 5–9 require a future ranker selection lock."
        )
    if args.batch_size <= 0:
        raise ValueError("Batch size must be positive.")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("protocol_version") != "rolling-temporal":
        raise ValueError("Expected rolling-temporal manifest.")
    fingerprint = manifest_fingerprint(manifest)
    require_completed_sweeps(args.sweep_dir, manifest)
    verify_fold_files(manifest, args.fold_dir, args.max_fold)
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Interactions do not match the rolling manifest.")
    configs = {
        name: json.loads((args.sweep_dir / f"{name}_sweep.json").read_text(encoding="utf-8"))[
            "selected_config"
        ]
        for name in ("item_knn", "als")
    }
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    if (
        reference.get("manifest_sha256") != fingerprint
        or reference.get("model_configs") != configs
        or reference.get("policy") != M7_POLICY
    ):
        raise ValueError("M7 reference does not match the selected rolling inputs and policy.")
    reference_rows = {
        row["fold_index"]: row
        for row in reference["results"]
        if row["cohort"] == "warm" and row["generator"] == "hybrid"
    }
    if set(reference_rows) != set(range(1, 10)):
        raise ValueError("M7 reference lacks complete warm hybrid folds.")
    expected = {
        "benchmark": "m10-causal-ranking-dataset",
        "protocol_version": manifest["protocol_version"],
        "manifest_sha256": fingerprint,
        "source_sha256": manifest["source_sha256"],
        "raw_property_sha256": manifest["raw_property_sha256"],
        "implementation_sha256": implementation_fingerprint(),
        "m7_reference_sha256": sha256_file(args.reference),
        "sweep_sha256": {
            name: sha256_file(args.sweep_dir / f"{name}_sweep.json") for name in configs
        },
        "model_configs": configs,
        "policy": POLICY,
        "m7_policy": M7_POLICY,
        "feature_schema": str(candidate_schema()),
        "request_schema": str(REQUEST_SCHEMA),
        "runtime": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "pyarrow": pa.__version__,
            "implicit": implicit.__version__,
            "psutil": psutil.__version__,
        },
        "blind_holdout": False,
    }
    if args.artifact.exists():
        artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
        validate_checkpoint(artifact, expected, args.output_dir)
    else:
        artifact = {
            **expected,
            "role": "development ranking data; no learned ranker or blind validation",
            "unit": "warm user-window",
            "folds": [],
        }
    interactions = pd.read_parquet(args.input_path)
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    for fold in manifest["folds"][: args.max_fold]:
        index = fold["fold_index"]
        if index <= len(artifact["folds"]):
            continue
        cutoff = int(fold["train_cutoff"])
        train = interactions.loc[interactions["timestamp"] <= cutoff]
        fold_path = args.fold_dir / f"fold_{index:02d}"
        catalog = pd.read_parquet(fold_path / "items_train.parquet")
        targets = pd.read_parquet(fold_path / "warm_targets.parquet")
        if len(train) != fold["training_interactions"] or len(targets) != fold["warm_target_users"]:
            raise ValueError("Ranking dataset fold row counts differ from rolling manifest.")
        if len(catalog) != fold["train_catalog_items"] or (
            not targets.empty
            and not (
                (targets["timestamp"] > cutoff)
                & (targets["timestamp"] <= fold["evaluation_cutoff"])
            ).all()
        ):
            raise ValueError(
                "Ranking dataset catalog or targets differ from rolling fold boundaries."
            )
        print(f"Ranking dataset fold {index}: fit, retrieve and write ranking rows", flush=True)
        row = write_fold(
            index=index,
            cutoff=cutoff,
            evaluation_cutoff=fold["evaluation_cutoff"],
            train=train,
            catalog=catalog,
            targets=targets,
            configs=configs,
            output_dir=args.output_dir,
            batch_size=args.batch_size,
            reference_row=reference_rows[index],
        )
        artifact["folds"].append(row)
        save_checkpoint(args.artifact, artifact)
        print(
            f"Saved Ranking dataset fold {index}: {row['positives']:,}/{row['requests']:,} hits",
            flush=True,
        )
        del train, catalog, targets
    print(f"Saved {args.artifact}", flush=True)


if __name__ == "__main__":
    main()
