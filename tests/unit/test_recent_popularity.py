import pandas as pd
import pytest

from ecommerce_recsys.recommendation.recent_popularity import RecentPopularityRecommender

# Reference timestamp: T = 1_000_000_000_000 ms
T = 1_000_000_000_000
DAY_MS = 24 * 60 * 60 * 1000  # 86_400_000 ms


@pytest.fixture()
def interactions():
    """
    Item A: 5 interactions, all at T - 60 days -> outside 30-day window
    Item B: 1 interaction at T - 5 days -> inside window
    Item C: 2 interactions at T - 10 days -> inside window

    Global ranking: A > C > B
    Recent ranking: C > B (A fully excluded)
    """
    return pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u1", "u1", "u1", "u2", "u3", "u3"],
            "item_id": ["A", "A", "A", "A", "A", "B", "C", "C"],
            "timestamp": [
                T - 60 * DAY_MS,  # A - outside window
                T - 60 * DAY_MS,
                T - 60 * DAY_MS,
                T - 60 * DAY_MS,
                T - 60 * DAY_MS,
                T - 5 * DAY_MS,  # B - inside window
                T - 10 * DAY_MS,  # C - inside window
                T - 10 * DAY_MS,
            ],
        }
    )


def test_recent_differs_from_global(interactions):
    """Items outside the window are excluded despite higher total counts."""
    rec = RecentPopularityRecommender(window_days=30)
    rec.fit(interactions)

    ranking = rec.recommend(3)

    assert "A" not in ranking  # A is outside the window
    assert ranking[0] == "C"  # C has 2 recent interactions
    assert ranking[1] == "B"  # B has 1 recent interaction


def test_recommend_returns_at_most_k(interactions):
    rec = RecentPopularityRecommender(window_days=30)
    rec.fit(interactions)

    assert len(rec.recommend(1)) == 1
    assert len(rec.recommend(2)) == 2


def test_recommend_invalid_k(interactions):
    rec = RecentPopularityRecommender(window_days=30)
    rec.fit(interactions)

    with pytest.raises(ValueError, match="k must be positive"):
        rec.recommend(0)


def test_fit_requires_item_id():
    rec = RecentPopularityRecommender()

    with pytest.raises(ValueError, match="item_id"):
        rec.fit(pd.DataFrame({"user_id": ["u1"], "timestamp": [T]}))


def test_recommend_before_fit_raises():
    rec = RecentPopularityRecommender()
    with pytest.raises(RuntimeError, match="fit"):
        rec.recommend(5)


def test_fit_requires_timestamp():
    rec = RecentPopularityRecommender()

    with pytest.raises(ValueError, match="timestamp"):
        rec.fit(pd.DataFrame({"user_id": ["u1"], "item_id": ["A"]}))
