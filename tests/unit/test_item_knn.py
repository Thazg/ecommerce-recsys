import pandas as pd
import pytest

from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender


@pytest.fixture()
def interactions():
    """
    3 users, 4 items, min_item_interactions=1 để test dễ hơn.

    User u1: A, B, C
    User u2: A, B
    User u3: A, C

    → A và B cùng xuất hiện ở u1, u2   → sim(A,B) cao
    → A và C cùng xuất hiện ở u1, u3   → sim(A,C) cao
    → B và C chỉ cùng xuất hiện ở u1   → sim(B,C) thấp hơn
    """
    return pd.DataFrame(
        {
            "user_id": ["u1", "u1", "u1", "u2", "u2", "u3", "u3"],
            "item_id": ["A", "B", "C", "A", "B", "A", "C"],
        }
    )


def test_recommend_excludes_seen(interactions):
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    # User đã thấy A → A không được xuất hiện trong kết quả
    result = rec.recommend(user_history=["A"], k=5)
    assert "A" not in result


def test_recommend_returns_at_most_k(interactions):
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    result = rec.recommend(user_history=["A"], k=1)
    assert len(result) == 1

    result = rec.recommend(user_history=["A"], k=2)
    assert len(result) == 2


def test_recommend_empty_history(interactions):
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    assert rec.recommend(user_history=[], k=5) == []


def test_recommend_before_fit_raises():
    rec = ItemKNNRecommender()
    with pytest.raises(RuntimeError, match="fit"):
        rec.recommend(user_history=["A"], k=5)


def test_recommend_invalid_k(interactions):
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    with pytest.raises(ValueError, match="k must be positive"):
        rec.recommend(user_history=["A"], k=0)


def test_set_shrinkage_lambda_updates_value():
    rec = ItemKNNRecommender(shrinkage_lambda=0.0)

    rec.set_shrinkage_lambda(100.0)

    assert rec._shrinkage_lambda == 100.0


def test_set_shrinkage_lambda_rejects_negative_value():
    rec = ItemKNNRecommender()

    with pytest.raises(ValueError, match="shrinkage_lambda"):
        rec.set_shrinkage_lambda(-1.0)


def test_fit_requires_user_id():
    rec = ItemKNNRecommender(min_item_interactions=1)
    with pytest.raises(ValueError, match="user_id"):
        rec.fit(pd.DataFrame({"item_id": ["A", "B"]}))


def test_fit_requires_item_id():
    rec = ItemKNNRecommender(min_item_interactions=1)
    with pytest.raises(ValueError, match="item_id"):
        rec.fit(pd.DataFrame({"user_id": ["u1", "u2"]}))


def test_similarity_based_ranking(interactions):
    """
    User history = [C].
    C cùng user với A (u1, u3) và B (chỉ u1).
    → A phải ranked cao hơn B vì sim(C,A) > sim(C,B).
    """
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    result = rec.recommend(user_history=["C"], k=2)

    assert result[0] == "A"  # A similar hơn B với C
    assert "C" not in result  # C đã seen


def test_unknown_history_item_uses_popularity_fallback(interactions):
    """Item không có trong training space → không có neighbors → trả về popularity fallback."""
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    result = rec.recommend(user_history=["UNKNOWN_ITEM"], k=5)
    assert result == ["A", "B", "C"]
