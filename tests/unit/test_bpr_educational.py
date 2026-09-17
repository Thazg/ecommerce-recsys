import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.recommendation.bpr_educational import (
    EducationalBPR,
)


def test_constructor_rejects_invalid_factors():
    with pytest.raises(ValueError, match="factors must be positive"):
        EducationalBPR(factors=0)


def test_constructor_rejects_invalid_learning_rate():
    with pytest.raises(ValueError, match="learning_rate must be positive"):
        EducationalBPR(learning_rate=0)


def test_constructor_rejects_negative_regularization():
    with pytest.raises(
        ValueError,
        match="regularization must be non-negative",
    ):
        EducationalBPR(regularization=-0.1)


def test_constructor_rejects_invalid_epochs():
    with pytest.raises(ValueError, match="epochs must be positive"):
        EducationalBPR(epochs=0)


def test_fit_builds_user_and_item_mappings():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=2,
        epochs=1,
        random_state=42,
    )

    model.fit(interactions)

    assert model._user_to_index == {
        "u1": 0,
        "u2": 1,
    }

    assert model._item_to_index == {
        "i1": 0,
        "i2": 1,
        "i3": 2,
    }


def test_fit_initializes_factor_matrices():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=4,
        epochs=1,
        random_state=42,
    )

    model.fit(interactions)

    assert model._user_factors is not None
    assert model._item_factors is not None

    assert model._user_factors.shape == (2, 4)
    assert model._item_factors.shape == (3, 4)


def test_sample_training_triplets_contains_positive_and_unobserved_negative():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model = EducationalBPR(
        factors=2,
        epochs=1,
        random_state=42,
    )

    model._build_mappings(interactions)

    triplets = model._sample_training_triplets(
        interactions,
        negative_samples=1,
    )

    assert len(triplets) == len(interactions)

    observed_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

    for _, row in triplets.iterrows():
        user_id = row["user_id"]
        positive_item = row["positive_item_id"]
        negative_item = row["negative_item_id"]

        assert positive_item in observed_by_user[user_id]
        assert negative_item not in observed_by_user[user_id]
        assert positive_item != negative_item


def test_sample_training_triplets_supports_multiple_negatives():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model = EducationalBPR(
        factors=2,
        epochs=1,
        random_state=42,
    )

    model._build_mappings(interactions)

    triplets = model._sample_training_triplets(
        interactions,
        negative_samples=2,
    )

    assert len(triplets) == 4 * 2


def test_sample_training_triplets_rejects_non_positive_negative_samples():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(factors=2, epochs=1)
    model._build_mappings(interactions)

    with pytest.raises(
        ValueError,
        match="negative_samples must be positive",
    ):
        model._sample_training_triplets(
            interactions,
            negative_samples=0,
        )


def test_predict_returns_dot_product_score():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u2"],
            "item_id": ["i1", "i2"],
        }
    )

    model = EducationalBPR(
        factors=2,
        epochs=1,
        random_state=42,
    )
    model.fit(interactions)

    model._user_factors[:] = np.array(
        [
            [1.0, 2.0],
            [0.0, 1.0],
        ]
    )

    model._item_factors[:] = np.array(
        [
            [3.0, 4.0],
            [2.0, 1.0],
        ]
    )

    assert model.predict("u1", "i1") == pytest.approx(11.0)


def test_update_factors_increases_positive_score_relative_to_negative():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=2,
        learning_rate=0.1,
        regularization=0.0,
        random_state=42,
    )
    model.fit(interactions)

    model._user_factors[:] = np.array([[1.0, 0.0]])
    model._item_factors[:] = np.array(
        [
            [0.0, 0.0],  # i1 positive
            [1.0, 0.0],  # i2 negative
            [0.0, 0.0],  # i3 unused
        ]
    )

    positive_before = model.predict("u1", "i1")
    negative_before = model.predict("u1", "i2")

    model._update_factors(
        user_id="u1",
        positive_item_id="i1",
        negative_item_id="i2",
    )

    positive_after = model.predict("u1", "i1")
    negative_after = model.predict("u1", "i2")

    assert positive_after - negative_after > positive_before - negative_before


def test_compute_loss_is_lower_when_positive_score_is_higher():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=2,
        regularization=0.0,
        random_state=42,
    )
    model.fit(interactions)

    triplets = pd.DataFrame(
        {
            "user_id": ["u1"],
            "positive_item_id": ["i1"],
            "negative_item_id": ["i2"],
        }
    )

    model._user_factors[:] = np.array([[1.0, 0.0]])
    model._item_factors[:] = np.array(
        [
            [2.0, 0.0],  # i1
            [0.0, 0.0],  # i2
            [0.0, 0.0],  # i3 unused
        ]
    )

    loss_when_positive_higher = model._compute_loss(triplets)

    model._item_factors[:] = np.array(
        [
            [0.0, 0.0],  # i1
            [2.0, 0.0],  # i2
            [0.0, 0.0],  # i3 unused
        ]
    )

    loss_when_negative_higher = model._compute_loss(triplets)

    assert loss_when_positive_higher < loss_when_negative_higher


def test_fit_learns_positive_over_negative_preference():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=2,
        learning_rate=0.05,
        regularization=0.001,
        epochs=20,
        random_state=42,
    )

    model.fit(interactions)

    positive_score = model.predict("u1", "i1")
    negative_score = model.predict("u1", "i2")

    assert positive_score > negative_score


def test_recommend_returns_top_unseen_items():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalBPR(
        factors=2,
        random_state=42,
    )
    model.fit(interactions)

    model._user_factors[:] = np.array(
        [
            [1.0, 0.0],  # u1
            [0.0, 1.0],  # u2
        ]
    )

    model._item_factors[:] = np.array(
        [
            [5.0, 0.0],  # i1 - seen by u1
            [4.0, 0.0],  # i2 - seen by u1
            [3.0, 0.0],  # i3 - unseen by u1
        ]
    )

    recommendations = model.recommend("u1", k=2)

    assert recommendations == ["i3"]
