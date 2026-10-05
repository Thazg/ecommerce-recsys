"""Reproduce the historical per-user leave-last-out split (not globally causal)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from ecommerce_recsys.data.splitting import (
    temporal_leave_last_out_split,
    verify_temporal_invariants,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-path",
        type=Path,
        default=Path("data/processed/interactions.parquet"),
        help="Path to interactions.parquet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Target directory for split Parquet files",
    )
    parser.add_argument(
        "--min-interactions",
        type=int,
        default=3,
        help="Minimum interactions for user evaluation eligibility (default: 3)",
    )

    args = parser.parse_args()
    if not args.input_path.exists():
        print(f"[ERROR] Input file not found: {args.input_path}")
        return 1

    print(f"\n[1/3] Loading interactions from {args.input_path.resolve()} ...")
    t0 = time.time()
    df = pd.read_parquet(args.input_path)
    total_events = len(df)
    print(f"      Loaded {total_events:,} events in {time.time() - t0:.2f}s")

    print("\n[2/3] Performing User Leave-Last-Out temporal split ...")
    df_train, df_val, df_test = temporal_leave_last_out_split(df, args.min_interactions)

    print("      Checking within-user time order only (historical protocol) ...")
    verify_temporal_invariants(df_train, df_val, df_test)
    print("      [PASSED] Within-user ordering; global leakage is possible.")

    print("\n[3/3] Saving split Parquet files ...")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    train_path = args.output_dir / "train.parquet"
    val_path = args.output_dir / "val.parquet"
    test_path = args.output_dir / "test.parquet"

    df_train.to_parquet(train_path, index=False, engine="pyarrow", compression="snappy")
    df_val.to_parquet(val_path, index=False, engine="pyarrow", compression="snappy")
    df_test.to_parquet(test_path, index=False, engine="pyarrow", compression="snappy")

    print(
        f"      Train : {len(df_train):>10,} rows ({len(df_train) / total_events * 100:.2f}%) -> {train_path.name}"
    )
    print(
        f"      Val   : {len(df_val):>10,} rows ({len(df_val) / total_events * 100:.2f}%) -> {val_path.name}"
    )
    print(
        f"      Test  : {len(df_test):>10,} rows ({len(df_test) / total_events * 100:.2f}%) -> {test_path.name}"
    )
    print(
        f"      Total : {len(df_train) + len(df_val) + len(df_test):>10,} rows (100.0% preserved)"
    )
    print(f"\n[SUCCESS] Split completed in {time.time() - t0:.2f}s total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
