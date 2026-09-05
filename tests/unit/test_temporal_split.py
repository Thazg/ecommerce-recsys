"""Unit tests for temporal leave-last-out splitting and zero data leakage.

Milestone 3 — Temporal Split and Offline Evaluation Harness.
"""

import pandas as pd
import pytest

from ecommerce_recsys.data.splitting import (
    temporal_leave_last_out_split,
    verify_temporal_invariants,
)


@pytest.fixture
def sample_interactions_df() -> pd.DataFrame:
    """Create deterministic interaction sequence for testing splits."""
    records = [
        # User A: 5 interactions (eligible)
        {"user_id": "user_a", "item_id": "i1", "timestamp": 100, "event_type": "view"},
        {"user_id": "user_a", "item_id": "i2", "timestamp": 200, "event_type": "view"},
        {"user_id": "user_a", "item_id": "i3", "timestamp": 300, "event_type": "view"},
        {"user_id": "user_a", "item_id": "i4", "timestamp": 400, "event_type": "addtocart"},
        {"user_id": "user_a", "item_id": "i4", "timestamp": 500, "event_type": "transaction"},
        # User B: 3 interactions (eligible)
        {"user_id": "user_b", "item_id": "i1", "timestamp": 150, "event_type": "view"},
        {"user_id": "user_b", "item_id": "i3", "timestamp": 250, "event_type": "view"},
        {"user_id": "user_b", "item_id": "i5", "timestamp": 350, "event_type": "addtocart"},
        # User C: 2 interactions (ineligible for test/val, kept in train)
        {"user_id": "user_c", "item_id": "i2", "timestamp": 120, "event_type": "view"},
        {"user_id": "user_c", "item_id": "i6", "timestamp": 220, "event_type": "view"},
    ]
    return pd.DataFrame(records)


def test_temporal_split_sizes(sample_interactions_df):
    train, val, test = temporal_leave_last_out_split(
        sample_interactions_df,
        min_user_interactions=3,
    )

    # User A (5 events) -> 3 train, 1 val, 1 test
    # User B (3 events) -> 1 train, 1 val, 1 test
    # User C (2 events) -> 2 train, 0 val, 0 test
    assert len(train) == 6
    assert len(val) == 2
    assert len(test) == 2
    assert len(train) + len(val) + len(test) == len(sample_interactions_df)


def test_zero_temporal_leakage(sample_interactions_df):
    train, val, test = temporal_leave_last_out_split(
        sample_interactions_df,
        min_user_interactions=3,
    )

    # Invariants should pass without error
    verify_temporal_invariants(train, val, test)


def test_val_and_test_exact_items(sample_interactions_df):
    _, val, test = temporal_leave_last_out_split(
        sample_interactions_df,
        min_user_interactions=3,
    )

    val_lookup = val.set_index("user_id")["item_id"].to_dict()
    test_lookup = test.set_index("user_id")["item_id"].to_dict()

    assert val_lookup["user_a"] == "i4"
    assert test_lookup["user_a"] == "i4"
    assert val_lookup["user_b"] == "i3"
    assert test_lookup["user_b"] == "i5"
