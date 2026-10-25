"""Build processed interactions and items Parquet artifacts.

Milestone 2 — Data Quality, EDA, and Interaction Semantics.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from ecommerce_recsys.data.schemas import EventType


def _validate_events(df: pd.DataFrame) -> None:
    """Validate the raw integer contract before normalization or persistence."""
    required = {"timestamp", "visitorid", "event", "itemid", "transactionid"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required event columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("Events must not be empty.")

    for column in ("timestamp", "visitorid", "itemid", "transactionid"):
        values = df[column]
        if column == "transactionid":
            values = values.dropna()
        if not values.str.fullmatch(r"[0-9]+").fillna(False).all():
            raise ValueError(f"{column} must contain non-negative integers without nulls.")
        try:
            df[column] = df[column].astype("Int64" if column == "transactionid" else "int64")
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"{column} must fit in a signed 64-bit integer.") from error

    if (df["timestamp"] <= 0).any():
        raise ValueError("timestamp must contain positive integer milliseconds.")
    if not df["event"].isin([event.value for event in EventType]).all():
        raise ValueError("event must be view, addtocart or transaction, without nulls.")


def process_interactions(events_path: Path, output_path: Path) -> pd.DataFrame:
    """Read raw events, sort chronologically, format canonical columns, and save Parquet."""
    print(f"\n[1/3] Processing interactions from {events_path.resolve()} ...")
    t0 = time.time()
    # Preserve integer text exactly: nullable IDs must not round through float64.
    df = pd.read_csv(
        events_path,
        dtype=dict.fromkeys(("timestamp", "visitorid", "itemid", "transactionid"), "string"),
    )
    _validate_events(df)

    # 1. Sort strictly by timestamp ascending
    df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)

    # 2. Canonical Column Mapping
    df["user_id"] = df["visitorid"].astype(str)
    df["item_id"] = df["itemid"].astype(str)
    df["event_type"] = df["event"].astype(str)
    df["timestamp"] = df["timestamp"].astype("int64")
    df["transaction_id"] = df["transactionid"].astype("Int64")

    # 3. Behavioral flags and UTC datetime
    df["is_view"] = df["event_type"] == "view"
    df["is_cart"] = df["event_type"] == "addtocart"
    df["is_purchase"] = df["event_type"] == "transaction"
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    # 4. Select ordered canonical columns
    canonical_cols = [
        "user_id",
        "item_id",
        "timestamp",
        "event_type",
        "datetime",
        "is_view",
        "is_cart",
        "is_purchase",
        "transaction_id",
    ]
    df_out = df[canonical_cols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(output_path, index=False, engine="pyarrow", compression="snappy")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"      Saved {len(df_out):,} interactions to {output_path.name}")
    print(f"      Size: {size_mb:.2f} MB (took {time.time() - t0:.2f}s)")
    return df_out


def extract_item_metadata(
    raw_dir: Path,
    df_interactions: pd.DataFrame,
    output_path: Path,
) -> None:
    """Aggregate item interaction stats, extract category IDs, and save items Parquet."""
    print("\n[2/3] Extracting item catalog metadata ...")
    t0 = time.time()

    # 1. Item activity counts from interactions
    item_stats = (
        df_interactions.groupby("item_id")
        .agg(
            total_interactions=("event_type", "count"),
            view_count=("is_view", "sum"),
            cart_count=("is_cart", "sum"),
            purchase_count=("is_purchase", "sum"),
            first_seen=("timestamp", "min"),
            last_seen=("timestamp", "max"),
        )
        .reset_index()
    )

    # 2. Extract category mapping from item properties
    cat_mapping = {}
    prop_files = [
        raw_dir / "item_properties_part1.csv",
        raw_dir / "item_properties_part2.csv",
    ]

    for p in prop_files:
        if not p.exists():
            continue
        print(f"      Scanning {p.name} for category IDs ...")
        for chunk in pd.read_csv(p, usecols=["itemid", "property", "value"], chunksize=2_000_000):
            cats = chunk[chunk["property"] == "categoryid"]
            for _, row in cats.iterrows():
                cat_mapping[str(row["itemid"])] = str(row["value"])

    item_stats["category_id"] = item_stats["item_id"].map(cat_mapping)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    item_stats.to_parquet(output_path, index=False, engine="pyarrow", compression="snappy")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    has_cat = item_stats["category_id"].notnull().sum()
    print(f"      Saved {len(item_stats):,} unique items to {output_path.name}")
    print(f"      Items with category mapped: {has_cat:,} ({has_cat / len(item_stats) * 100:.1f}%)")
    print(f"      Size: {size_mb:.2f} MB (took {time.time() - t0:.2f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build processed recsys datasets.")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to data/raw directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Path to data/processed directory",
    )

    args = parser.parse_args()
    raw_dir = args.raw_dir
    output_dir = args.output_dir

    events_path = raw_dir / "events.csv"
    if not events_path.exists():
        print(f"[ERROR] events.csv not found in {raw_dir}")
        return 1

    t_start = time.time()
    interactions_path = output_dir / "interactions.parquet"
    items_path = output_dir / "items.parquet"

    df_interactions = process_interactions(events_path, interactions_path)
    extract_item_metadata(raw_dir, df_interactions, items_path)

    print(f"\n[3/3] Data pipeline finished successfully in {time.time() - t_start:.2f}s total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
