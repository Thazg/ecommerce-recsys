"""Exploratory Data Analysis (EDA) for Retailrocket raw interaction data.

Milestone 2 — Data Quality, EDA, and Interaction Semantics.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def analyze_events(events_path: Path) -> dict:
    """Read events.csv and compute core recommendation EDA metrics."""
    print(f"\n[INFO] Loading {events_path.resolve()} ...")
    df = pd.read_csv(events_path)

    total_rows = len(df)
    unique_users = df["visitorid"].nunique()
    unique_items = df["itemid"].nunique()

    # 1. Event Type Distribution
    event_counts = df["event"].value_counts()
    event_pcts = (event_counts / total_rows * 100).round(2)

    # 2. Conversion Funnel (per user level)
    users_with_view = set(df[df["event"] == "view"]["visitorid"])
    users_with_cart = set(df[df["event"] == "addtocart"]["visitorid"])
    users_with_buy = set(df[df["event"] == "transaction"]["visitorid"])

    # 3. User Activity Distribution
    user_counts = df.groupby("visitorid").size()
    user_quantiles = user_counts.quantile([0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).to_dict()
    users_1_event = int((user_counts == 1).sum())
    users_1_event_pct = round(users_1_event / unique_users * 100, 2)
    users_3plus = int((user_counts >= 3).sum())
    users_3plus_pct = round(users_3plus / unique_users * 100, 2)
    users_5plus = int((user_counts >= 5).sum())
    users_5plus_pct = round(users_5plus / unique_users * 100, 2)

    # 4. Item Popularity Distribution
    item_counts = df.groupby("itemid").size()
    item_quantiles = item_counts.quantile([0.5, 0.75, 0.9, 0.99]).to_dict()
    top_1pct_item_count = max(1, int(unique_items * 0.01))
    top_1pct_events = item_counts.nlargest(top_1pct_item_count).sum()
    top_1pct_events_pct = round(top_1pct_events / total_rows * 100, 2)

    # 5. Temporal Span
    min_ts = df["timestamp"].min()
    max_ts = df["timestamp"].max()
    dt_start = datetime.fromtimestamp(min_ts / 1000, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc)
    duration_days = round((max_ts - min_ts) / (1000 * 86400), 1)

    # 6. Repeated Interactions (same user + same item)
    pair_counts = df.groupby(["visitorid", "itemid"]).size()
    repeated_pairs = int((pair_counts > 1).sum())
    total_pairs = len(pair_counts)
    repeated_pairs_pct = round(repeated_pairs / total_pairs * 100, 2)

    # 7. Null Check
    null_counts = df.isnull().sum().to_dict()

    metrics = {
        "total_rows": total_rows,
        "unique_users": unique_users,
        "unique_items": unique_items,
        "event_counts": event_counts.to_dict(),
        "event_percentages": event_pcts.to_dict(),
        "users_view": len(users_with_view),
        "users_cart": len(users_with_cart),
        "users_buy": len(users_with_buy),
        "user_quantiles": user_quantiles,
        "users_1_event": users_1_event,
        "users_1_event_pct": users_1_event_pct,
        "users_3plus": users_3plus,
        "users_3plus_pct": users_3plus_pct,
        "users_5plus": users_5plus,
        "users_5plus_pct": users_5plus_pct,
        "item_quantiles": item_quantiles,
        "top_1pct_events_pct": top_1pct_events_pct,
        "start_date": dt_start.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "end_date": dt_end.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "duration_days": duration_days,
        "total_user_item_pairs": total_pairs,
        "repeated_pairs": repeated_pairs,
        "repeated_pairs_pct": repeated_pairs_pct,
        "null_counts": null_counts,
    }

    return metrics


def print_eda_report(m: dict) -> None:
    """Print clean terminal executive report."""
    print("=" * 60)
    print("RETAILROCKET EXPLORATORY DATA ANALYSIS (EDA) REPORT")
    print("=" * 60)

    print("\n1. Overall Dataset Scale:")
    print(f"   Total Interactions:  {m['total_rows']:,}")
    print(f"   Unique Users:        {m['unique_users']:,}")
    print(f"   Unique Items:        {m['unique_items']:,}")
    print(f"   Time Period:         {m['start_date']} to {m['end_date']}")
    print(f"   Duration:            {m['duration_days']} days (~4.5 months)")

    print("\n2. Event Funnel Distribution:")
    for event, count in m["event_counts"].items():
        pct = m["event_percentages"][event]
        print(f"   - {event:<12}: {count:>10,} ({pct}%)")

    cart_conv = round(m["users_cart"] / m["users_view"] * 100, 2)
    buy_conv = round(m["users_buy"] / m["users_view"] * 100, 2)
    print(
        f"   * User Funnel: {m['users_view']:,} viewed "
        f"-> {m['users_cart']:,} carted ({cart_conv}%) "
        f"-> {m['users_buy']:,} purchased ({buy_conv}%)"
    )

    print("\n3. User Activity & Sparsity:")
    print(f"   Users with only 1 event : {m['users_1_event']:,} ({m['users_1_event_pct']}%)")
    print(f"   Users with >= 3 events  : {m['users_3plus']:,} ({m['users_3plus_pct']}%)")
    print(f"   Users with >= 5 events  : {m['users_5plus']:,} ({m['users_5plus_pct']}%)")
    print("   Activity Percentiles:")
    for q, val in m["user_quantiles"].items():
        print(f"     p{int(float(q) * 100):<2}: {val:.1f} events")

    print("\n4. Item Popularity & Long-Tail:")
    print(
        f"   Top 1% most popular items account for: {m['top_1pct_events_pct']}% of all interactions"
    )
    print("   Item Interaction Percentiles:")
    for q, val in m["item_quantiles"].items():
        print(f"     p{int(float(q) * 100):<2}: {val:.1f} events")

    print("\n5. Repeated Interactions:")
    print(f"   Total unique (user, item) pairs: {m['total_user_item_pairs']:,}")
    print(
        f"   Pairs with > 1 interaction:      {m['repeated_pairs']:,} ({m['repeated_pairs_pct']}%)"
    )

    print("\n6. Missing Values Check:")
    for col, nulls in m["null_counts"].items():
        print(f"   - {col:<15}: {nulls:,} nulls")
    print("=" * 60)


def generate_notebook(m: dict, nb_path: Path) -> None:
    """Generate a clean 01_data_understanding.ipynb notebook."""
    cells = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# Milestone 2 — Data Understanding and EDA\n",
                "\n",
                "This notebook analyzes the Retailrocket raw dataset to understand:\n",
                "- Behavioral funnel distribution (view, addtocart, transaction)\n",
                "- User activity sparsity and cold-start proportions\n",
                "- Item popularity and long-tail decay\n",
                "- Repeated interactions and duplicate behaviors\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from pathlib import Path\n",
                "import pandas as pd\n",
                "\n",
                "raw_events_path = Path('../data/raw/events.csv')\n",
                "df = pd.read_csv(raw_events_path)\n",
                "print(f'Total events loaded: {len(df):,}')\n",
                "df.head()\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Event Type Breakdown\n",
                "df['event'].value_counts(normalize=True).mul(100).round(2)\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# User Activity Distribution\n",
                "user_counts = df.groupby('visitorid').size()\n",
                "print(f'Proportion of users with exactly 1 interaction: {(user_counts == 1).mean():.2%}')\n",
                "user_counts.quantile([0.5, 0.75, 0.9, 0.95, 0.99])\n",
            ],
        },
    ]

    notebook_content = {
        "cells": cells,
        "metadata": {
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    nb_path.parent.mkdir(parents=True, exist_ok=True)
    with nb_path.open("w", encoding="utf-8") as f:
        json.dump(notebook_content, f, indent=2)

    print(f"\n[INFO] Generated notebook: {nb_path.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Retailrocket EDA.")
    parser.add_argument(
        "--events-path",
        type=Path,
        default=Path("data/raw/events.csv"),
        help="Path to events.csv",
    )
    parser.add_argument(
        "--notebook-path",
        type=Path,
        default=Path("notebooks/01_data_understanding.ipynb"),
        help="Target notebook path",
    )

    args = parser.parse_args()
    if not args.events_path.exists():
        print(f"[ERROR] Events file not found at: {args.events_path}")
        return 1

    metrics = analyze_events(args.events_path)
    print_eda_report(metrics)
    generate_notebook(metrics, args.notebook_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
