import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.data.catalog import build_train_catalog
from ecommerce_recsys.evaluation.benchmark import _calculate_latency_metrics, evaluate_recommender
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.recommendation.recent_popularity import (
    MS_PER_DAY,
    RecentPopularityRecommender,
)
from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever


def test_recency_gap_uses_same_explicit_cutoff_for_ranking_and_retrieval():
    train = pd.DataFrame(
        {
            "user_id": ["v"] * 10 + ["v", "u"],
            "item_id": ["A"] * 10 + ["B", "C"],
            "timestamp": [2 * MS_PER_DAY] * 10 + [31 * MS_PER_DAY] * 2,
        }
    )
    cutoff = 60 * MS_PER_DAY
    model = RecentPopularityRecommender(30)
    model.fit(train, cutoff=cutoff)
    retriever = PopularityRetriever(train, ["A", "B", "C"], window_days=30, cutoff=cutoff)
    assert model.recommend(10) == ["B", "C"]
    assert [c.item_id for c in retriever.generate(RetrievalContext(), 10)] == ["B", "C"]
    target = pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [cutoff + 1]})
    result = evaluate_recommender(model, train, target, k_values=(1,), train_cutoff=cutoff)
    assert result["HR@1"] == 1
    with pytest.raises(ValueError, match="targets must follow"):
        evaluate_recommender(model, train, target.assign(timestamp=cutoff), train_cutoff=cutoff)
    with pytest.raises(ValueError, match="Training interactions follow"):
        evaluate_recommender(model, train, target, train_cutoff=30 * MS_PER_DAY)
    model.fit(train, cutoff=100 * MS_PER_DAY)
    assert model.recommend(10) == []
    with pytest.raises(ValueError, match="follow"):
        model.fit(train, cutoff=30 * MS_PER_DAY)


def test_catalog_can_update_metadata_inside_gap_before_declared_cutoff(tmp_path):
    properties = pd.DataFrame(
        {
            "timestamp": [5, 12, 16],
            "itemid": ["A"] * 3,
            "property": ["categoryid"] * 3,
            "value": ["old", "current", "future"],
        }
    )
    properties.to_csv(tmp_path / "item_properties_part1.csv", index=False)
    properties.iloc[:0].to_csv(tmp_path / "item_properties_part2.csv", index=False)
    train = pd.DataFrame({"item_id": ["A"], "timestamp": [10]})
    assert build_train_catalog(train, tmp_path, cutoff=15).iloc[0]["category_id"] == "current"
    assert build_train_catalog(train, tmp_path).iloc[0]["category_id"] == "old"
    with pytest.raises(ValueError, match="follow"):
        build_train_catalog(train, tmp_path, cutoff=9)


@pytest.mark.parametrize("samples", [[], [0.001], [0, 0.001, 0.003, 0.012]])
def test_latency_uses_shared_linear_quantiles(samples):
    shared = latency_metrics(samples)
    ranking = _calculate_latency_metrics(samples)
    for key, value in ranking.items():
        assert value == round(shared[key], 6)
    for q in (50, 95, 99):
        expected = np.percentile(np.asarray(samples) * 1000, q, method="linear") if samples else 0
        assert shared[f"latency_p{q}_ms"] == expected


@pytest.mark.parametrize("samples", [[-1], [np.nan], [np.inf]])
def test_latency_rejects_invalid_samples(samples):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        latency_metrics(samples)
