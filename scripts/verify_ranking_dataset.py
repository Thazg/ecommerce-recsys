"""Independently audit persisted ranking Parquet and checkpoint counts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ecommerce_recsys.data.rolling_provenance import sha256_file
from ecommerce_recsys.ranking.dataset import ABSENT_SOURCE_RANK, CANDIDATE_BUDGET, SOURCE_NAMES


def audit_fold(fold_dir: Path, expected: dict) -> dict:
    requests_path = fold_dir / "requests.parquet"
    candidates_path = fold_dir / "candidates.parquet"
    if (
        sha256_file(requests_path) != expected["requests_sha256"]
        or sha256_file(candidates_path) != expected["candidates_sha256"]
    ):
        raise ValueError("Ranking dataset persisted files differ from quality checkpoint.")
    requests = pd.read_parquet(requests_path)
    if requests.isna().any().any() or requests["request_id"].duplicated().any():
        raise ValueError("Ranking dataset request file has nulls or duplicate keys.")
    if not (
        len(requests) == expected["requests"]
        and int(requests["pool_size"].sum()) == expected["candidates"]
        and int(requests["target_in_pool"].sum()) == expected["positives"]
        and int(requests["target_in_catalog"].sum()) == expected["reachable"]
    ):
        raise ValueError("Ranking dataset request file totals differ from checkpoint.")
    if not (
        requests["pool_size"].between(0, CANDIDATE_BUDGET).all()
        and (requests["target_in_pool"] <= requests["target_in_catalog"]).all()
    ):
        raise ValueError("Ranking dataset request reachability or pool bounds are invalid.")
    total_rows = 0
    total_positive = 0
    nulls = 0
    nonfinite = 0
    unknown_category = 0
    source_absent = {name: 0 for name in SOURCE_NAMES}
    request_lookup = requests.set_index("request_id")[
        ["target_item_id", "pool_size", "target_in_pool"]
    ].to_dict("index")
    completed_requests: set[str] = set()
    active_request: str | None = None
    active_count = 0
    active_positives = 0
    active_items: set[str] = set()

    def finish_request() -> None:
        if active_request is None:
            return
        expected_request = request_lookup[active_request]
        if (
            active_count != expected_request["pool_size"]
            or active_positives != expected_request["target_in_pool"]
        ):
            raise ValueError("Ranking dataset candidate group does not reconcile with its request.")
        completed_requests.add(active_request)

    previous_request: str | None = None
    previous_rank = 0
    parquet = pq.ParquetFile(candidates_path)
    for batch in parquet.iter_batches(batch_size=50_000):
        total_rows += batch.num_rows
        nulls += sum(batch.column(i).null_count for i in range(batch.num_columns))
        frame = batch.to_pandas()
        ranks = frame["retrieval_rank"].to_numpy()
        request_ids = frame["request_id"].to_numpy()
        items = frame["item_id"].to_numpy()
        labels = frame["label"].to_numpy()
        boundaries = np.r_[0, np.flatnonzero(request_ids[1:] != request_ids[:-1]) + 1, len(frame)]
        for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
            key = request_ids[start]
            if key != active_request:
                finish_request()
                if key in completed_requests or key not in request_lookup:
                    raise ValueError(
                        "Ranking dataset candidate request is duplicated or unknown across batches."
                    )
                active_request = key
                active_count = 0
                active_positives = 0
                active_items = set()
            group_items = items[start:end]
            if len(set(group_items)) != len(group_items) or active_items.intersection(group_items):
                raise ValueError("Ranking dataset candidate item is duplicated within a request.")
            active_items.update(group_items)
            expected_labels = (group_items == request_lookup[key]["target_item_id"]).astype(int)
            if not np.array_equal(labels[start:end], expected_labels):
                raise ValueError("Ranking dataset candidate label differs from its request target.")
            active_count += end - start
            active_positives += int(labels[start:end].sum())
        if len(frame):
            same = request_ids[1:] == request_ids[:-1]
            required = np.where(same, ranks[:-1] + 1, 1)
            if not np.array_equal(ranks[1:], required):
                raise ValueError(
                    "Ranking dataset candidate ranks are not consecutive within requests."
                )
            if ranks[0] != (previous_rank + 1 if request_ids[0] == previous_request else 1):
                raise ValueError(
                    "Ranking dataset candidate ranks are not consecutive across batches."
                )
            previous_request = request_ids[-1]
            previous_rank = int(ranks[-1])
        if not frame["retrieval_rank"].between(1, CANDIDATE_BUDGET).all():
            raise ValueError("Ranking dataset candidate rank is outside the retrieval budget.")
        if not frame["label"].isin([0, 1]).all():
            raise ValueError("Ranking dataset label is not binary.")
        total_positive += int(frame["label"].sum())
        unknown_category += int((frame["category_known"] == 0).sum())
        for name in frame.select_dtypes(include="number"):
            nonfinite += int((~np.isfinite(frame[name].to_numpy())).sum())
        present_count = np.zeros(len(frame), dtype=np.int8)
        for source in SOURCE_NAMES:
            present = frame[f"{source}_present"].to_numpy()
            rank = frame[f"{source}_rank"].to_numpy()
            score = frame[f"{source}_score"].to_numpy()
            if not np.isin(present, [0, 1]).all():
                raise ValueError("Ranking dataset source presence is not binary.")
            absent = present == 0
            source_absent[source] += int(absent.sum())
            if not (
                np.all(rank[absent] == ABSENT_SOURCE_RANK)
                and np.all(score[absent] == 0)
                and np.all((rank[~absent] >= 1) & (rank[~absent] <= CANDIDATE_BUDGET))
            ):
                raise ValueError("Ranking dataset absent/present source evidence is inconsistent.")
            present_count += present
        if not np.array_equal(present_count, frame["source_count"].to_numpy()):
            raise ValueError("Ranking dataset source count differs from evidence flags.")
    finish_request()
    if completed_requests != {key for key, row in request_lookup.items() if row["pool_size"] > 0}:
        raise ValueError("Ranking dataset candidate groups do not match nonempty requests.")
    if (
        total_rows != expected["candidates"]
        or total_positive != expected["positives"]
        or nulls
        or nonfinite
    ):
        raise ValueError("Ranking dataset candidate totals, nulls or finite-value checks failed.")
    return {
        "fold_index": expected["fold_index"],
        "requests": len(requests),
        "candidates": total_rows,
        "positives": total_positive,
        "null_feature_values": nulls,
        "nonfinite_numeric_values": nonfinite,
        "unknown_category_candidate_rows": unknown_category,
        "absent_source_rows": source_absent,
        "requests_sha256": expected["requests_sha256"],
        "candidates_sha256": expected["candidates_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quality", type=Path, default=Path("benchmarks/ranking/m10_quality_v1.json")
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/ranking/m10_v1"))
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/ranking/m10_feature_audit_v1.json")
    )
    args = parser.parse_args()
    quality = json.loads(args.quality.read_text(encoding="utf-8"))
    if [row["fold_index"] for row in quality.get("folds", [])] != [1, 2, 3, 4]:
        raise ValueError("Ranking dataset feature audit requires complete development folds 1–4.")
    rows = [
        audit_fold(args.data_dir / f"fold_{fold['fold_index']:02d}", fold)
        for fold in quality["folds"]
    ]
    artifact = {
        "benchmark": "m10-ranking-feature-audit",
        "quality_sha256": sha256_file(args.quality),
        "verifier_sha256": hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "folds": rows,
    }
    artifact["payload_sha256"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    pending = args.output.with_suffix(args.output.suffix + ".tmp")
    pending.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(args.output)
    print(f"Verified {sum(row['candidates'] for row in rows):,} rows in {args.output}")


if __name__ == "__main__":
    main()
