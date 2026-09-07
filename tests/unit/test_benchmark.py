import pandas as pd
import pytest

from ecommerce_recsys.evaluation.benchmark import (
    _build_ground_truth,
    _build_user_histories,
    evaluate_recommender,
    run_baseline_benchmark,
)
from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)
from ecommerce_recsys.recommendation.popularity import PopularityRecommender
from ecommerce_recsys.recommendation.recent_popularity import (
    RecentPopularityRecommender,
)


@pytest.fixture()
def train() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": [
                "u1",
                "u1",
                "u2",
                "u2",
                "u3",
                "u3",
            ],
            "item_id": [
                "A",
                "B",
                "A",
                "C",
                "B",
                "C",
            ],
            "timestamp": [
                1,
                2,
                1,
                2,
                1,
                2,
            ],
        }
    )


@pytest.fixture()
def test() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": ["u1", "u2", "u3"],
            "item_id": ["C", "B", "A"],
            "timestamp": [3, 3, 3],
        }
    )


def test_build_ground_truth(test: pd.DataFrame) -> None:
    assert _build_ground_truth(test) == {
        "u1": "C",
        "u2": "B",
        "u3": "A",
    }


def test_build_user_histories(train: pd.DataFrame) -> None:
    histories = _build_user_histories(train)

    assert histories == {
        "u1": ["A", "B"],
        "u2": ["A", "C"],
        "u3": ["B", "C"],
    }


def test_evaluate_popularity(train: pd.DataFrame, test: pd.DataFrame) -> None:
    recommender = PopularityRecommender()

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=test,
        k_values=(1, 2),
        total_catalog_items=3,
    )

    assert set(metrics) == {
        "HR@1",
        "MRR@1",
        "NDCG@1",
        "HR@2",
        "MRR@2",
        "NDCG@2",
        "coverage",
        "latency_avg_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
    }

    assert 0.0 <= metrics["HR@1"] <= 1.0
    assert 0.0 <= metrics["MRR@1"] <= 1.0
    assert 0.0 <= metrics["NDCG@1"] <= 1.0
    assert 0.0 <= metrics["coverage"] <= 1.0
    assert metrics["latency_avg_ms"] >= 0.0
    assert metrics["latency_p50_ms"] >= 0.0
    assert metrics["latency_p95_ms"] >= 0.0
    assert metrics["latency_p99_ms"] >= 0.0


def test_evaluate_item_knn(
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> None:
    recommender = ItemKNNRecommender(
        n_neighbors=2,
        min_item_interactions=1,
    )

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=test,
        k_values=(1, 2),
        total_catalog_items=3,
    )

    assert "HR@1" in metrics
    assert "MRR@2" in metrics
    assert "NDCG@2" in metrics
    assert "coverage" in metrics


def test_evaluate_als(
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> None:
    recommender = MatrixFactorizationRecommender(
        factors=2,
        iterations=5,
        regularization=0.01,
    )

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=test,
        k_values=(1, 2),
        total_catalog_items=3,
    )

    assert "HR@1" in metrics
    assert "MRR@2" in metrics
    assert "NDCG@2" in metrics
    assert "coverage" in metrics


def test_run_baseline_benchmark(
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> None:
    recommenders = {
        "Popularity": PopularityRecommender(),
        "RecentPopularity": RecentPopularityRecommender(
            window_days=30,
        ),
        "ItemKNN": ItemKNNRecommender(
            n_neighbors=2,
            min_item_interactions=1,
        ),
        "ALS": MatrixFactorizationRecommender(
            factors=2,
            iterations=5,
            regularization=0.01,
        ),
    }

    results = run_baseline_benchmark(
        train=train,
        test=test,
        recommenders=recommenders,
        k_values=(1, 2),
        total_catalog_items=3,
    )

    assert set(results) == {
        "Popularity",
        "RecentPopularity",
        "ItemKNN",
        "ALS",
    }

    for model_name, metrics in results.items():
        assert model_name in recommenders
        assert "HR@1" in metrics
        assert "MRR@1" in metrics
        assert "NDCG@1" in metrics
        assert "coverage" in metrics


def test_empty_recommenders_rejected(
    train: pd.DataFrame,
    test: pd.DataFrame,
) -> None:
    with pytest.raises(
        ValueError,
        match="At least one recommender is required",
    ):
        run_baseline_benchmark(
            train=train,
            test=test,
            recommenders={},
        )


def test_empty_test_returns_empty_metrics(
    train: pd.DataFrame,
) -> None:
    test = pd.DataFrame(columns=["user_id", "item_id", "timestamp"])

    recommender = PopularityRecommender()

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=test,
    )

    assert metrics == {}
