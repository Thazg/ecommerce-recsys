from __future__ import annotations

import pandas as pd
import pytest

from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)


@pytest.fixture
def interactions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": [
                "user_1",
                "user_1",
                "user_2",
                "user_2",
                "user_3",
                "user_3",
            ],
            "item_id": [
                "item_1",
                "item_2",
                "item_2",
                "item_3",
                "item_3",
                "item_4",
            ],
        }
    )


def test_fit_builds_user_item_mappings(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    assert recommender._user_to_index == {
        "user_1": 0,
        "user_2": 1,
        "user_3": 2,
    }

    assert recommender._item_to_index == {
        "item_1": 0,
        "item_2": 1,
        "item_3": 2,
        "item_4": 3,
    }


def test_fit_builds_user_item_matrix(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    assert recommender._user_item_matrix is not None
    assert recommender._user_item_matrix.shape == (3, 4)

    assert recommender._user_item_matrix[0, 0] == 1.0
    assert recommender._user_item_matrix[0, 1] == 1.0
    assert recommender._user_item_matrix[1, 1] == 1.0
    assert recommender._user_item_matrix[1, 2] == 1.0


def test_fit_creates_als_model(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    assert recommender._model is not None


def test_recommend_returns_item_ids(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    recommendations = recommender.recommend(
        "user_1",
        k=2,
    )

    assert isinstance(recommendations, list)
    assert len(recommendations) <= 2
    assert all(item_id in recommender._item_to_index for item_id in recommendations)


def test_recommend_filters_already_liked_items(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    recommendations = recommender.recommend(
        "user_1",
        k=2,
    )

    already_liked = {"item_1", "item_2"}

    assert already_liked.isdisjoint(recommendations)
    assert len(recommendations) <= 2
    assert len(set(recommendations)) == len(recommendations)


def test_recommend_unknown_user_returns_empty_list(
    interactions: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    recommender.fit(interactions)

    recommendations = recommender.recommend(
        "unknown_user",
        k=10,
    )

    assert recommendations == []


def test_recommend_before_fit_raises() -> None:
    recommender = MatrixFactorizationRecommender()

    with pytest.raises(
        RuntimeError,
        match="Model has not been fitted",
    ):
        recommender.recommend("user_1")


def test_fit_empty_interactions_raises() -> None:
    recommender = MatrixFactorizationRecommender()

    interactions = pd.DataFrame(columns=["user_id", "item_id"])

    with pytest.raises(
        ValueError,
        match="Interactions must not be empty",
    ):
        recommender.fit(interactions)


def test_fit_missing_required_column_raises() -> None:
    recommender = MatrixFactorizationRecommender()

    interactions = pd.DataFrame(
        {
            "user_id": ["user_1"],
        }
    )

    with pytest.raises(
        ValueError,
        match="Missing required columns",
    ):
        recommender.fit(interactions)
