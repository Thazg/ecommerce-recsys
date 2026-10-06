import pandas as pd
import pytest

from ecommerce_recsys.evaluation.candidates import (
    CandidateMetrics,
    evaluate_candidate_sources,
    summarize_candidates,
    validate_targets,
)
from ecommerce_recsys.retrieval.base import Candidate, SourceEvidence
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever


def candidate(item):
    return Candidate(item, 1.0, (SourceEvidence("global_popularity", 1.0, 1),))


def test_candidate_recall_keeps_unreachable_targets_in_primary_denominator():
    metrics = CandidateMetrics(frozenset(["A", "B"]), (1, 2))
    metrics.add("A", [candidate("A"), candidate("B")])
    metrics.add("new", [])
    result = metrics.output()
    assert result["metrics"]["Recall@1"] == 0.5
    assert result["metrics"]["reachable_recall@1"] == 1.0
    assert result["metrics"]["mean_candidates@2"] == 1.0
    assert result["metrics"]["empty_rate@2"] == 0.5
    assert result["totals"]["2"]["source_target_hits"] == {"global_popularity": 1}


def test_shared_cold_evaluation_matches_individual_requests():
    candidates = [candidate("A"), candidate("B")]
    individual = CandidateMetrics(frozenset(["A", "B"]), (1, 2))
    shared = CandidateMetrics(frozenset(["A", "B"]), (1, 2))
    for target in ["A", "A", "B", "new"]:
        individual.add(target, candidates)
    shared.add_shared({"A": 2, "B": 1, "new": 1}, candidates)
    assert shared.output() == individual.output()


def test_empty_metrics_are_finite_and_pooling_uses_exact_totals():
    metrics = CandidateMetrics(frozenset(), (1,))
    assert set(metrics.output()["metrics"].values()) == {0.0}
    one = CandidateMetrics(frozenset(["A"]), (1,))
    one.add("A", [candidate("A")])
    three = CandidateMetrics(frozenset(["A"]), (1,))
    three.add("new", [], 3)
    rows = [
        {"cohort": "warm", "generator": "g", "fold_index": i, **m.output()}
        for i, m in enumerate([one, three], 1)
    ]
    assert summarize_candidates(rows)["warm/g"]["pooled_metrics"]["Recall@1"] == 0.25


@pytest.fixture
def train():
    return pd.DataFrame({"user_id": ["u", "v"], "item_id": ["A", "B"], "timestamp": [1, 2]})


def test_evaluator_checks_causality_seen_targets_and_cohort(train):
    target = pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [3]})
    validate_targets(train, target, "warm")
    with pytest.raises(ValueError, match="Temporal leakage"):
        validate_targets(train, target.assign(timestamp=2), "warm")
    with pytest.raises(ValueError, match="already seen"):
        validate_targets(train, target.assign(item_id="A"), "warm")
    with pytest.raises(ValueError, match="cold cohort"):
        validate_targets(train, target, "cold")
    with pytest.raises(ValueError, match="warm cohort"):
        validate_targets(train, target.assign(user_id="unknown"), "warm")
    with pytest.raises(ValueError, match="one target"):
        validate_targets(train, pd.concat([target, target]), "warm")


def test_warm_and_cold_full_pipeline_with_source_evidence(train):
    source = PopularityRetriever(train, ["A", "B"])
    hybrid = HybridCandidateGenerator([source], pool_size=2)
    warm = pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [3]})
    rows = evaluate_candidate_sources(
        train, warm, [source], [hybrid], cohort="warm", n_values=(1, 2)
    )
    assert len(rows) == 2
    assert all(row["metrics"]["Recall@1"] == 1 for row in rows)
    assert all(row["metrics"]["mean_candidates@2"] == 1 for row in rows)
    cold = warm.assign(user_id="new")
    rows = evaluate_candidate_sources(
        train, cold, [source], [hybrid], cohort="cold", n_values=(1, 2), cold_latency_samples=2
    )
    assert all(row["metrics"]["Recall@1"] == 0 for row in rows)
    assert all(row["metrics"]["Recall@2"] == 1 for row in rows)
    assert all(row["latency_samples"] == 2 for row in rows)
    assert all(row["totals"]["2"]["source_target_hits"] == {source.name: 1} for row in rows)


def test_mixed_id_types_cannot_bypass_seen_target_guard():
    train = pd.DataFrame({"user_id": [1], "item_id": [2], "timestamp": [1]})
    target = pd.DataFrame({"user_id": ["1"], "item_id": ["2"], "timestamp": [2]})
    with pytest.raises(ValueError, match="already seen"):
        validate_targets(train, target, "warm")


def test_warm_evaluator_merges_histories_for_ids_normalized_to_same_string():
    train = pd.DataFrame(
        {
            "user_id": [1, "1", "other"],
            "item_id": ["A", "B", "C"],
            "timestamp": [1, 2, 3],
        }
    )
    target = pd.DataFrame({"user_id": ["1"], "item_id": ["C"], "timestamp": [4]})
    source = PopularityRetriever(train, ["A", "B", "C"])

    rows = evaluate_candidate_sources(train, target, [source], [], cohort="warm", n_values=(1,))

    assert rows[0]["metrics"]["Recall@1"] == 1.0
    assert rows[0]["totals"]["1"]["hits"] == 1


def test_empty_cold_cohort_emits_zero_without_latency_samples(train):
    targets = train.iloc[:0].copy()
    source = PopularityRetriever(train, ["A", "B"])
    rows = evaluate_candidate_sources(train, targets, [source], [], cohort="cold", n_values=(1, 2))
    assert rows[0]["evaluation_users"] == 0
    assert rows[0]["latency_samples"] == 0
    assert set(rows[0]["metrics"].values()) == {0.0}
