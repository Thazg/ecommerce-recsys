"""Data splitting algorithms and temporal leakage verification.

Milestone 3 — Temporal Split and Offline Evaluation Harness.
"""

from __future__ import annotations

import pandas as pd


def temporal_leave_last_out_split(
    df: pd.DataFrame,
    min_user_interactions: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split interactions into train, val, and test using User Leave-Last-Out protocol."""
    # Ensure stable sorting by user and timestamp
    df = df.sort_values(
        ["user_id", "timestamp"],
        ascending=[True, True],
        kind="stable",
    ).reset_index(drop=True)

    # Compute interaction index from end for each user (0 = last, 1 = second to last)
    user_totals = df.groupby("user_id")["timestamp"].transform("count")
    user_cumcount = df.groupby("user_id").cumcount()
    reverse_idx = user_totals - 1 - user_cumcount

    is_eligible = user_totals >= min_user_interactions
    is_test = is_eligible & (reverse_idx == 0)
    is_val = is_eligible & (reverse_idx == 1)
    is_train = ~is_test & ~is_val

    df_train = (
        df[is_train]
        .drop(columns=["user_interaction_idx", "reverse_idx"], errors="ignore")
        .reset_index(drop=True)
    )
    df_val = (
        df[is_val]
        .drop(columns=["user_interaction_idx", "reverse_idx"], errors="ignore")
        .reset_index(drop=True)
    )
    df_test = (
        df[is_test]
        .drop(columns=["user_interaction_idx", "reverse_idx"], errors="ignore")
        .reset_index(drop=True)
    )

    return df_train, df_val, df_test


def verify_temporal_invariants(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    df_test: pd.DataFrame,
) -> None:
    """Verify that no temporal leakage exists between splits for eligible users."""
    train_max_ts = df_train.groupby("user_id")["timestamp"].max()
    val_ts = df_val.set_index("user_id")["timestamp"]
    test_ts = df_test.set_index("user_id")["timestamp"]

    # Invariant 1: val timestamp must be >= max train timestamp (strictly less is leakage)
    common_val_train = val_ts.index.intersection(train_max_ts.index)
    val_leakage = (val_ts.loc[common_val_train] < train_max_ts.loc[common_val_train]).sum()

    # Invariant 2: test timestamp must be >= val timestamp
    common_test_val = test_ts.index.intersection(val_ts.index)
    test_leakage = (test_ts.loc[common_test_val] < val_ts.loc[common_test_val]).sum()

    if val_leakage > 0 or test_leakage > 0:
        raise ValueError(
            f"True temporal leakage detected! Val leakage: {val_leakage}, Test leakage: {test_leakage}"
        )
