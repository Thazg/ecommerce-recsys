"""Data splitting algorithms and temporal leakage verification.

Milestone 3 — Temporal Split and Offline Evaluation Harness.
"""

from __future__ import annotations

import pandas as pd


def rolling_temporal_cutoffs(df: pd.DataFrame, n_windows: int = 10) -> list[int]:
    """Return strictly increasing global cutoffs for equal timestamp-count windows."""
    if "timestamp" not in df or df.empty or df["timestamp"].isna().any():
        raise ValueError("Nonempty interactions with timestamps are required.")
    if n_windows < 2:
        raise ValueError("n_windows must be at least 2.")
    timestamps = sorted(df["timestamp"].unique())
    if len(timestamps) < n_windows:
        raise ValueError("At least n_windows distinct timestamps are required.")
    return [
        int(timestamps[int(len(timestamps) * window / n_windows) - 1])
        for window in range(1, n_windows)
    ] + [int(timestamps[-1])]


def rolling_temporal_fold(
    df: pd.DataFrame,
    cutoffs: list[int],
    fold_index: int,
    min_train_interactions: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return train, unseen warm targets, cold targets, and all events in one window."""
    required = {"user_id", "item_id", "timestamp"}
    if not required.issubset(df.columns) or df[list(required)].isna().any().any():
        raise ValueError("Non-null user_id, item_id, and timestamp columns are required.")
    if min_train_interactions < 1:
        raise ValueError("min_train_interactions must be positive.")
    if not 1 <= fold_index < len(cutoffs):
        raise ValueError("fold_index must select a window after the first training window.")
    if cutoffs != sorted(set(cutoffs)):
        raise ValueError("cutoffs must be strictly increasing.")

    train_cutoff = cutoffs[fold_index - 1]
    evaluation_cutoff = cutoffs[fold_index]
    train = df.loc[df["timestamp"] <= train_cutoff]
    window = df.loc[(df["timestamp"] > train_cutoff) & (df["timestamp"] <= evaluation_cutoff)]
    if train.empty or window.empty:
        raise ValueError("Training and evaluation windows must be nonempty.")

    train_counts = train.groupby("user_id").size()
    warm_users = set(train_counts[train_counts >= min_train_interactions].index)
    all_train_users = set(train_counts.index)
    ordered_window = window.sort_values(["timestamp", "user_id", "item_id"], kind="stable")
    warm_events = ordered_window.loc[ordered_window["user_id"].isin(warm_users)]
    known_pairs = pd.MultiIndex.from_frame(train[["user_id", "item_id"]].drop_duplicates())
    unseen = ~pd.MultiIndex.from_frame(warm_events[["user_id", "item_id"]]).isin(known_pairs)
    warm_targets = warm_events.loc[unseen].drop_duplicates("user_id", keep="first")
    cold_targets = ordered_window.loc[
        ~ordered_window["user_id"].isin(all_train_users)
    ].drop_duplicates("user_id", keep="first")

    if not warm_targets.empty:
        verify_global_train_before_target(train, warm_targets)
        verify_unseen_targets(train, warm_targets)
    if not cold_targets.empty:
        verify_global_train_before_target(train, cold_targets)
    return train, warm_targets.reset_index(drop=True), cold_targets.reset_index(drop=True), window


def temporal_leave_last_out_split(
    df: pd.DataFrame,
    min_user_interactions: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Legacy per-user split retained for reproducing historical benchmarks.

    This does not provide a global training cutoff. New benchmarks must use
    rolling_temporal_fold instead.
    """
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


def verify_temporal_invariants(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame) -> None:
    """Check historical per-user ordering only; this does not prove global causality."""
    for frame in (train, val, test):
        if not {"user_id", "timestamp"}.issubset(frame.columns):
            raise ValueError("Each split requires user_id and timestamp.")
    if not val["user_id"].equals(test["user_id"]):
        if set(val["user_id"]) != set(test["user_id"]):
            raise ValueError("Validation and test users differ.")
    train_max = train.groupby("user_id")["timestamp"].max()
    val_times = val.set_index("user_id")["timestamp"]
    test_times = test.set_index("user_id")["timestamp"]
    if (train_max.reindex(val_times.index) > val_times).any():
        raise ValueError("Training follows validation for a user.")
    if (val_times > test_times).any():
        raise ValueError("Validation follows test for a user.")


def verify_global_train_before_target(train: pd.DataFrame, target: pd.DataFrame) -> None:
    """Reject evaluation data that overlaps the model's training time."""
    if "timestamp" not in train or "timestamp" not in target:
        raise ValueError("Both training and evaluation data require timestamps.")
    if train.empty or target.empty:
        raise ValueError("Training and evaluation data must be nonempty.")
    if not train["timestamp"].max() < target["timestamp"].min():
        raise ValueError("Temporal leakage: training overlaps evaluation globally.")


def verify_unseen_targets(train: pd.DataFrame, target: pd.DataFrame) -> None:
    """Require discovery targets that are absent from each user's training history."""
    train_pairs = pd.MultiIndex.from_frame(train[["user_id", "item_id"]].drop_duplicates())
    target_pairs = pd.MultiIndex.from_frame(target[["user_id", "item_id"]])
    if target_pairs.isin(train_pairs).any():
        raise ValueError("Evaluation contains targets already seen by their users in training.")
