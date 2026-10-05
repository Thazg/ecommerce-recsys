from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.recommendation.matrix_factorization_educational import (
    EducationalMatrixFactorization,
)


def test_mixed_id_types_and_equal_scores_are_deterministic():
    interactions = pd.DataFrame({"user_id": [1, "2", 3], "item_id": [1, "2", 3]})
    model = EducationalMatrixFactorization(factors=2, epochs=1)
    model.fit(interactions)
    model._user_factors[:] = 0.0
    model._item_factors[:] = 0.0

    assert model.recommend(1, k=2) == ["2", "3"]


@pytest.fixture
def interactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": ["u2", "u1", "u3", "u1"],
            "item_id": ["i2", "i1", "i3", "i2"],
        }
    )


def test_default_configuration() -> None:
    model = EducationalMatrixFactorization()

    assert model.factors == 8
    assert model.learning_rate == 0.01
    assert model.regularization == 0.01
    assert model.epochs == 20
    assert model.random_state == 42
    assert model._fitted is False


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("factors", 0),
        ("factors", -1),
        ("learning_rate", 0),
        ("learning_rate", -0.01),
        ("regularization", -0.01),
        ("epochs", 0),
        ("epochs", -1),
    ],
)
def test_invalid_configuration(parameter: str, value: float) -> None:
    with pytest.raises(ValueError):
        EducationalMatrixFactorization(**{parameter: value})


def test_build_mappings(interactions: pd.DataFrame) -> None:
    model = EducationalMatrixFactorization()

    model._build_mappings(interactions)

    assert model._user_to_index == {
        "u1": 0,
        "u2": 1,
        "u3": 2,
    }
    assert model._item_to_index == {
        "i1": 0,
        "i2": 1,
        "i3": 2,
    }

    assert model._index_to_user == ["u1", "u2", "u3"]
    assert model._index_to_item == ["i1", "i2", "i3"]


def test_initialize_factors() -> None:
    model = EducationalMatrixFactorization(factors=4, random_state=42)

    model._initialize_factors(n_users=3, n_items=5)

    assert model._user_factors is not None
    assert model._item_factors is not None

    assert model._user_factors.shape == (3, 4)
    assert model._item_factors.shape == (5, 4)

    assert np.issubdtype(model._user_factors.dtype, np.floating)
    assert np.issubdtype(model._item_factors.dtype, np.floating)

    assert not np.all(model._user_factors == 0)
    assert not np.all(model._item_factors == 0)


def test_initialize_factors_is_reproducible() -> None:
    model_a = EducationalMatrixFactorization(
        factors=4,
        random_state=42,
    )
    model_b = EducationalMatrixFactorization(
        factors=4,
        random_state=42,
    )

    model_a._initialize_factors(n_users=3, n_items=5)
    model_b._initialize_factors(n_users=3, n_items=5)

    assert np.array_equal(
        model_a._user_factors,
        model_b._user_factors,
    )
    assert np.array_equal(
        model_a._item_factors,
        model_b._item_factors,
    )


def test_predict_returns_dot_product(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(factors=2)

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    assert model._user_factors is not None
    assert model._item_factors is not None

    model._user_factors[model._user_to_index["u1"]] = np.array([2.0, 3.0])
    model._item_factors[model._item_to_index["i2"]] = np.array([4.0, 5.0])

    prediction = model.predict("u1", "i2")

    assert prediction == pytest.approx(23.0)


def test_predict_rejects_unknown_user(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization()

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    with pytest.raises(ValueError, match="Unknown user_id"):
        model.predict("unknown_user", "i1")


def test_predict_rejects_unknown_item(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization()

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    with pytest.raises(ValueError, match="Unknown item_id"):
        model.predict("u1", "unknown_item")


def test_predict_before_fit_raises_runtime_error(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization()

    model._build_mappings(interactions)

    with pytest.raises(RuntimeError, match="not been fitted"):
        model.predict("u1", "i1")


def test_fit_builds_mappings_and_initializes_factors(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(factors=4)

    result = model.fit(interactions)

    assert result is model
    assert model._fitted is True

    assert model._user_factors is not None
    assert model._item_factors is not None

    assert model._user_factors.shape == (3, 4)
    assert model._item_factors.shape == (3, 4)


def test_fit_is_reproducible(
    interactions: pd.DataFrame,
) -> None:
    model_a = EducationalMatrixFactorization(
        factors=4,
        random_state=42,
    )
    model_b = EducationalMatrixFactorization(
        factors=4,
        random_state=42,
    )

    model_a.fit(interactions)
    model_b.fit(interactions)

    assert model_a._user_factors is not None
    assert model_b._user_factors is not None
    assert model_a._item_factors is not None
    assert model_b._item_factors is not None

    np.testing.assert_array_equal(
        model_a._user_factors,
        model_b._user_factors,
    )
    np.testing.assert_array_equal(
        model_a._item_factors,
        model_b._item_factors,
    )


def test_fit_requires_interaction_columns() -> None:
    model = EducationalMatrixFactorization()

    invalid_interactions = pd.DataFrame(
        {
            "user_id": ["u1"],
        }
    )

    with pytest.raises(KeyError):
        model.fit(invalid_interactions)


def test_fit_rejects_empty_interactions() -> None:
    model = EducationalMatrixFactorization()

    empty_interactions = pd.DataFrame(
        {
            "user_id": pd.Series(dtype=object),
            "item_id": pd.Series(dtype=object),
        }
    )

    with pytest.raises(ValueError, match="empty"):
        model.fit(empty_interactions)


def test_sample_training_examples_contains_positive_and_negative_samples(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(random_state=42)

    model._build_mappings(interactions)

    examples = model._sample_training_examples(
        interactions,
        negative_samples=1,
    )

    assert len(examples) == len(interactions) * 2

    assert set(examples["label"].unique()) == {0.0, 1.0}

    positive_examples = examples[examples["label"] == 1.0]

    assert len(positive_examples) == len(interactions)

    for _, row in interactions.iterrows():
        assert (
            (positive_examples["user_id"] == row["user_id"])
            & (positive_examples["item_id"] == row["item_id"])
        ).any()


def test_negative_samples_are_unobserved_for_each_user() -> None:
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model = EducationalMatrixFactorization(random_state=42)

    model._build_mappings(interactions)

    examples = model._sample_training_examples(
        interactions,
        negative_samples=2,
    )

    negative_examples = examples[examples["label"] == 0.0]

    observed_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

    for _, row in negative_examples.iterrows():
        assert row["item_id"] not in observed_by_user[row["user_id"]]


def test_negative_sampling_is_reproducible() -> None:
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model_a = EducationalMatrixFactorization(random_state=42)
    model_b = EducationalMatrixFactorization(random_state=42)

    model_a._build_mappings(interactions)
    model_b._build_mappings(interactions)

    examples_a = model_a._sample_training_examples(
        interactions,
        negative_samples=2,
    )
    examples_b = model_b._sample_training_examples(
        interactions,
        negative_samples=2,
    )

    pd.testing.assert_frame_equal(examples_a, examples_b)


def test_update_factors_moves_prediction_toward_target(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        learning_rate=0.1,
        regularization=0.0,
    )

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    assert model._user_factors is not None
    assert model._item_factors is not None

    user_index = model._user_to_index["u1"]
    item_index = model._item_to_index["i2"]

    model._user_factors[user_index] = np.array([1.0, 0.0])
    model._item_factors[item_index] = np.array([0.5, 0.0])

    prediction_before = model.predict("u1", "i2")

    model._update_factors(
        user_index=user_index,
        item_index=item_index,
        target=1.0,
    )

    prediction_after = model.predict("u1", "i2")

    assert prediction_before == pytest.approx(0.5)
    assert prediction_after > prediction_before


def test_update_factors_updates_both_user_and_item_vectors(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        learning_rate=0.1,
        regularization=0.0,
    )

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    assert model._user_factors is not None
    assert model._item_factors is not None

    user_index = model._user_to_index["u1"]
    item_index = model._item_to_index["i2"]

    model._user_factors[user_index] = np.array([1.0, 0.0])
    model._item_factors[item_index] = np.array([0.5, 0.0])

    user_before = model._user_factors[user_index].copy()
    item_before = model._item_factors[item_index].copy()

    model._update_factors(
        user_index=user_index,
        item_index=item_index,
        target=1.0,
    )

    assert not np.array_equal(
        model._user_factors[user_index],
        user_before,
    )
    assert not np.array_equal(
        model._item_factors[item_index],
        item_before,
    )


def test_update_factors_applies_regularization(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        learning_rate=0.1,
        regularization=0.5,
    )

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    assert model._user_factors is not None
    assert model._item_factors is not None

    user_index = model._user_to_index["u1"]
    item_index = model._item_to_index["i2"]

    model._user_factors[user_index] = np.array([1.0, 0.0])
    model._item_factors[item_index] = np.array([0.5, 0.0])

    user_before = model._user_factors[user_index].copy()
    item_before = model._item_factors[item_index].copy()

    model._update_factors(
        user_index=user_index,
        item_index=item_index,
        target=0.5,
    )

    # With zero prediction error, only L2 regularization changes
    # the vectors.
    assert model._user_factors[user_index][0] < user_before[0]
    assert model._item_factors[item_index][0] < item_before[0]


def test_fit_trains_factor_vectors(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        learning_rate=0.05,
        regularization=0.01,
        epochs=5,
        random_state=42,
    )

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    assert model._user_factors is not None
    assert model._item_factors is not None

    user_index = model._user_to_index["u1"]
    item_index = model._item_to_index["i2"]

    user_factors_before = model._user_factors.copy()
    item_factors_before = model._item_factors.copy()

    model.fit(interactions)

    assert model._fitted is True

    assert model._user_factors is not None
    assert model._item_factors is not None

    assert not np.array_equal(
        model._user_factors,
        user_factors_before,
    )
    assert not np.array_equal(
        model._item_factors,
        item_factors_before,
    )

    assert model.predict("u1", "i2") != pytest.approx(
        float(
            np.dot(
                user_factors_before[user_index],
                item_factors_before[item_index],
            )
        )
    )


def test_fit_training_is_reproducible(
    interactions: pd.DataFrame,
) -> None:
    model_a = EducationalMatrixFactorization(
        factors=4,
        learning_rate=0.05,
        regularization=0.01,
        epochs=5,
        random_state=42,
    )
    model_b = EducationalMatrixFactorization(
        factors=4,
        learning_rate=0.05,
        regularization=0.01,
        epochs=5,
        random_state=42,
    )

    model_a.fit(interactions)
    model_b.fit(interactions)

    assert model_a._user_factors is not None
    assert model_b._user_factors is not None
    assert model_a._item_factors is not None
    assert model_b._item_factors is not None

    np.testing.assert_array_equal(
        model_a._user_factors,
        model_b._user_factors,
    )
    np.testing.assert_array_equal(
        model_a._item_factors,
        model_b._item_factors,
    )


def test_compute_loss_returns_non_negative_value(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        regularization=0.01,
        random_state=42,
    )

    model.fit(interactions)

    loss = model._compute_loss(interactions)

    assert isinstance(loss, float)
    assert loss >= 0.0


def test_training_reduces_loss(
    interactions: pd.DataFrame,
) -> None:
    model = EducationalMatrixFactorization(
        factors=2,
        learning_rate=0.05,
        regularization=0.001,
        epochs=1,
        random_state=42,
    )

    model._build_mappings(interactions)
    model._initialize_factors(n_users=3, n_items=3)

    loss_before = model._compute_loss(interactions)

    model.fit(interactions)

    loss_after = model._compute_loss(interactions)

    assert loss_after < loss_before


def test_recommend_returns_items_in_descending_score_order():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model = EducationalMatrixFactorization(
        factors=1,
        epochs=1,
        random_state=42,
    )
    model.fit(interactions)

    model._user_factors[:] = np.array(
        [
            [1.0],
            [1.0],
        ]
    )
    model._item_factors[:] = np.array(
        [
            [0.1],  # i1 - seen
            [0.4],  # i2 - seen
            [0.8],  # i3 - unseen
            [0.2],  # i4 - unseen
        ]
    )

    recommendations = model.recommend("u1", k=2)

    assert recommendations == ["i3", "i4"]


def test_recommend_excludes_seen_items():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2", "u2"],
            "item_id": ["i1", "i2", "i3", "i4"],
        }
    )

    model = EducationalMatrixFactorization(
        factors=1,
        epochs=1,
        random_state=42,
    )
    model.fit(interactions)

    model._user_factors[:] = np.array(
        [
            [1.0],
            [1.0],
        ]
    )
    model._item_factors[:] = np.array(
        [
            [0.1],  # i1 - seen
            [0.9],  # i2 - seen
            [0.8],  # i3 - unseen
            [0.7],  # i4 - unseen
        ]
    )

    recommendations = model.recommend("u1", k=2)

    assert recommendations == ["i3", "i4"]
    assert "i1" not in recommendations
    assert "i2" not in recommendations


def test_recommend_rejects_unknown_user():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalMatrixFactorization(epochs=1)
    model.fit(interactions)

    with pytest.raises(ValueError, match="Unknown user_id"):
        model.recommend("unknown", k=2)


def test_recommend_rejects_non_positive_k():
    interactions = pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u2"],
            "item_id": ["i1", "i2", "i3"],
        }
    )

    model = EducationalMatrixFactorization(epochs=1)
    model.fit(interactions)

    with pytest.raises(ValueError, match="k must be positive"):
        model.recommend("u1", k=0)


def test_recommend_before_fit_raises_runtime_error():
    model = EducationalMatrixFactorization()

    with pytest.raises(RuntimeError, match="not been fitted"):
        model.recommend("u1", k=2)


@pytest.mark.parametrize("negative_samples", [0, -1])
def test_negative_sampling_requires_positive_count(
    interactions: pd.DataFrame,
    negative_samples: int,
) -> None:
    model = EducationalMatrixFactorization()

    model._build_mappings(interactions)

    with pytest.raises(ValueError, match="negative_samples"):
        model._sample_training_examples(
            interactions,
            negative_samples=negative_samples,
        )
