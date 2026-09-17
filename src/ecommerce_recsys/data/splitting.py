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
    required = {"user_id", "item_id", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if min_user_interactions < 3:
        raise ValueError("min_user_interactions must be >= 3 for leave-last-out (train/val/test).")

    if df.empty:
        raise ValueError("Input interactions must not be empty.")

    # Deterministic order: user_id -> timestamp -> item_id (stable for tied timestamps)
    df = df.sort_values(
        ["user_id", "timestamp", "item_id"],
        ascending=[True, True, True],
        kind="stable",
    ).reset_index(drop=True)

    user_totals = df.groupby("user_id")["timestamp"].transform("count")
    user_cumcount = df.groupby("user_id").cumcount()
    reverse_idx = user_totals - 1 - user_cumcount  # 0=last, 1=second-last

    is_eligible = user_totals >= min_user_interactions
    is_test = is_eligible & (reverse_idx == 0)
    is_val = is_eligible & (reverse_idx == 1)
    is_train = ~is_test & ~is_val

    df_train = df[is_train].reset_index(drop=True)
    df_val = df[is_val].reset_index(drop=True)
    df_test = df[is_test].reset_index(drop=True)

    return df_train, df_val, df_test


def verify_temporal_invariants(
    df_train: pd.DataFrame,
    df_val: pd.DataFrame,
    df_test: pd.DataFrame,
) -> None:
    """Verify that no temporal leakage exists between splits for eligible users."""
    if df_train.empty or df_val.empty or df_test.empty:
        # Empty split (e.g. all users ineligible): nothing to verify
        return

    train_max = df_train.groupby("user_id")["timestamp"].max()
    val_max = df_val.groupby("user_id")["timestamp"].max()
    test_max = df_test.groupby("user_id")["timestamp"].max()

    # 1. val must be strictly after max(train)
    common_val = val_max.index.intersection(train_max.index)
    val_leak = (val_max.loc[common_val] <= train_max.loc[common_val]).sum()

    # 2. test must be strictly after val
    common_test_val = test_max.index.intersection(val_max.index)
    test_val_leak = (test_max.loc[common_test_val] <= val_max.loc[common_test_val]).sum()

    # 3. test must be strictly after max(train)
    common_test_train = test_max.index.intersection(train_max.index)
    test_train_leak = (test_max.loc[common_test_train] <= train_max.loc[common_test_train]).sum()

    if val_leak > 0 or test_val_leak > 0 or test_train_leak > 0:
        raise ValueError(
            f"Temporal leakage! val<=train: {val_leak}, test<=val: {test_val_leak}, test<=train: {test_train_leak}"
        )
