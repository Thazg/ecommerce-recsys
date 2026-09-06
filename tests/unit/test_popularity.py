import pandas as pd
import pytest

from ecommerce_recsys.recommendation.popularity import PopularityRecommender


def test_popularity_ranks_items_by_interaction_count():
    interactions = pd.DataFrame(
        {
            "item_id": ["A", "B", "A", "C", "B", "A"],
        }
    )

    recommender = PopularityRecommender()
    recommender.fit(interactions)

    assert recommender.recommend(3) == ["A", "B", "C"]


def test_popularity_returns_at_most_k_items():
    interactions = pd.DataFrame(
        {
            "item_id": ["A", "B", "C"],
        }
    )

    recommender = PopularityRecommender()
    recommender.fit(interactions)

    assert recommender.recommend(2) == ["A", "B"]


def test_popularity_rejects_non_positive_k():
    recommender = PopularityRecommender()

    recommender.fit(pd.DataFrame({"item_id": ["A"]}))

    with pytest.raises(ValueError, match="k must be positive"):
        recommender.recommend(0)


def test_popularity_requires_item_id():
    recommender = PopularityRecommender()

    with pytest.raises(ValueError, match="item_id"):
        recommender.fit(pd.DataFrame({"user_id": ["u1"]}))
