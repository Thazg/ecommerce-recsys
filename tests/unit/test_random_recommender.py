import pandas as pd

from ecommerce_recsys.recommendation.random_recommender import RandomRecommender


def test_unknown_history_does_not_reduce_available_catalog():
    recommender = RandomRecommender(seed=42)
    recommender.fit(
        pd.DataFrame({"item_id": ["A"]}),
        pd.DataFrame({"item_id": ["A", "B"]}),
    )

    assert set(recommender.recommend("user", ["X", "Y"], 2)) == {"A", "B"}
    assert recommender.recommend("user", ["A", "X", "Y"], 2) == ["B"]
    assert recommender.recommend("user", ["A", "B", "X"], 2) == []


def test_dense_history_returns_all_remaining_items_without_duplicates():
    catalog = [str(item_id) for item_id in range(20)]
    recommender = RandomRecommender(seed=42)
    recommender.fit(
        pd.DataFrame({"item_id": catalog}),
        pd.DataFrame({"item_id": catalog}),
    )

    recommendations = recommender.recommend("user", catalog[:-2], 5)
    assert set(recommendations) == set(catalog[-2:])
    assert len(recommendations) == 2
