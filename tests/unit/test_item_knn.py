import pandas as pd
import pytest

from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender


@pytest.fixture()
def interactions():
    """
    3 users, 4 items, min_item_interactions=1 for simpler testing.

    User u1: A, B, C
    User u2: A, B
    User u3: A, C

    -> A and B co-occur in u1, u2 -> high sim(A,B)
    -> A and C co-occur in u1, u3 -> high sim(A,C)
    -> B and C co-occur only in u1 -> lower sim(B,C)
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

    # Seen item A must not appear in results
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
    C co-occurs with A (u1, u3) and B (only u1).
    -> A must rank above B because sim(C,A) > sim(C,B).
    """
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    result = rec.recommend(user_history=["C"], k=2)

    assert result[0] == "A"  # A is more similar to C than B
    assert "C" not in result  # C already seen


def test_unknown_history_item_uses_popularity_fallback(interactions):
    """Items outside the training space have no neighbors, so fall back to popularity."""
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    result = rec.recommend(user_history=["UNKNOWN_ITEM"], k=5)
    assert result == ["A", "B", "C"]


def test_tied_identical_items_do_not_become_their_own_neighbors():
    interactions = pd.DataFrame(
        {"user_id": ["u1", "u1", "u2", "u2"], "item_id": ["A", "B", "A", "B"]}
    )
    rec = ItemKNNRecommender(n_neighbors=1, min_item_interactions=1)
    rec.fit(interactions)

    assert [neighbor for neighbor, _, _ in rec._item_neighbors["A"]] == ["B"]
    assert [neighbor for neighbor, _, _ in rec._item_neighbors["B"]] == ["A"]


def test_sparse_cosine_uses_distinct_users_as_support(interactions):
    rec = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1)
    rec.fit(interactions)

    neighbors = {
        item: (similarity, support) for item, similarity, support in rec._item_neighbors["A"]
    }
    assert neighbors["B"][1] == 2
    assert neighbors["B"][0] == pytest.approx(2 / (3 * 2) ** 0.5)
