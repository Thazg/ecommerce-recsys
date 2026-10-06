from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.sparse import csr_matrix

from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender
from ecommerce_recsys.retrieval.base import Candidate, RetrievalContext, SourceEvidence
from ecommerce_recsys.retrieval.category_retriever import CategoryRetriever
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator
from ecommerce_recsys.retrieval.item_knn_retriever import ItemKNNRetriever
from ecommerce_recsys.retrieval.mf_retriever import MFRetriever
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever


@pytest.fixture
def train():
    return pd.DataFrame(
        {
            "user_id": ["u", "v", "v", "w", "w"],
            "item_id": ["A", "A", "B", "B", "C"],
            "timestamp": [1, 2, 3, 4, 5],
        }
    )


def ids(candidates):
    return [candidate.item_id for candidate in candidates]


def test_context_normalizes_and_deduplicates_ids():
    context = RetrievalContext(12, (3, "3", "A"))
    assert context.user_id == "12"
    assert context.history == ("3", "A")
    with pytest.raises(ValueError, match="null"):
        RetrievalContext(history=(None,))


@pytest.mark.parametrize("limit", [0, -1, 1.5, True])
def test_source_rejects_invalid_limits(train, limit):
    retriever = PopularityRetriever(train, ["A", "B", "C"])
    with pytest.raises(ValueError, match="positive integer"):
        retriever.generate(RetrievalContext(), limit)


def test_popularity_filters_catalog_and_seen_with_stable_ties(train):
    retriever = PopularityRetriever(train, ["A", "B"])
    assert ids(retriever.generate(RetrievalContext(), 9)) == ["A", "B"]
    candidates = retriever.generate(RetrievalContext(history=("A",)), 9)
    assert ids(candidates) == ["B"]
    assert candidates[0].evidence == (SourceEvidence("global_popularity", 2.0, 1),)
    assert retriever.generate(RetrievalContext(history=("A", "B")), 9) == []
    assert PopularityRetriever(train.iloc[:0], []).generate(RetrievalContext(), 2) == []


def test_recent_window_uses_declared_cutoff_and_rejects_future(train):
    retriever = PopularityRetriever(train, ["A", "B", "C"], window_days=1, cutoff=86_404_000)
    assert retriever.generate(RetrievalContext(), 10) == []
    with pytest.raises(ValueError, match="follow"):
        PopularityRetriever(train, ["A"], window_days=1, cutoff=3)


def test_category_pool_excludes_uncategorized_and_has_no_global_fallback(train):
    catalog = pd.DataFrame({"item_id": ["A", "B", "C"], "category_id": ["x", "x", None]})
    retriever = CategoryRetriever(train, catalog)
    candidates = retriever.generate(RetrievalContext(history=("A",)), 10)
    assert ids(candidates) == ["B"]
    assert candidates[0].score == 2.0
    assert retriever.generate(RetrievalContext(history=("unknown",)), 10) == []
    assert retriever.generate(RetrievalContext(), 10) == []


def test_knn_retains_real_similarity_without_unknown_history_fallback(train):
    model = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1, shrinkage_lambda=0)
    model.fit(train)
    retriever = ItemKNNRetriever(model, ["A", "B", "C"])
    candidates = retriever.generate(RetrievalContext(history=("A",)), 10)
    assert ids(candidates) == ["B"]
    assert candidates[0].score == pytest.approx(0.5)
    assert retriever.generate(RetrievalContext(history=("unknown",)), 10) == []
    assert retriever.generate(RetrievalContext(), 10) == []


def exact_model():
    model = MatrixFactorizationRecommender()
    model._model = SimpleNamespace(
        item_factors=np.array([[1.0], [0.5], [0.5], [-1.0]], dtype=np.float32),
        user_factors=np.array([[1.0]], dtype=np.float32),
    )
    model._user_item_matrix = csr_matrix([[1.0, 0.0, 0.0, 0.0]])
    model._user_to_index = {"u": 0}
    model._index_to_item = ["A", "B", "C", "D"]
    model._item_to_index = {item: i for i, item in enumerate(model._index_to_item)}
    return model


def test_exact_als_filters_training_and_request_history_and_exhaustion():
    model = exact_model()
    retriever = MFRetriever(model, ["A", "B", "C", "D"])
    assert ids(retriever.generate(RetrievalContext("u"), 1)) == ["B"]
    assert ids(retriever.generate(RetrievalContext("u"), 20)) == ["B", "C", "D"]
    candidates = retriever.generate(RetrievalContext("u", ("B",)), 20)
    assert ids(candidates) == ["C", "D"]
    assert candidates[-1].score == -1.0
    assert retriever.generate(RetrievalContext("u", ("B", "C", "D")), 20) == []
    assert retriever.generate(RetrievalContext("unknown", ("A",)), 20) == []
    assert retriever.generate(RetrievalContext(), 20) == []
    np.testing.assert_equal(model._model.item_factors[:, 0], [1, 0.5, 0.5, -1])


def test_als_rejects_incompatible_catalog_and_nonfinite_scores():
    model = exact_model()
    with pytest.raises(ValueError, match="catalog"):
        MFRetriever(model, ["B", "C"])
    model._model.item_factors[1, 0] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        MFRetriever(model, model.item_ids).generate(RetrievalContext("u"), 2)


def test_hybrid_deduplicates_retains_scores_and_has_prefix_consistency(train):
    global_source = PopularityRetriever(train, ["A", "B", "C"])
    recent = PopularityRetriever(train, ["A", "B", "C"], window_days=1, cutoff=5)
    hybrid = HybridCandidateGenerator([global_source, recent], pool_size=3)
    context = RetrievalContext(history=("A",))
    output = hybrid.generate(context, 3)
    assert ids(output) == ["B", "C"]
    assert output[0].score == pytest.approx(2 / 61)
    assert {e.source for e in output[0].evidence} == {"global_popularity", "recent_popularity"}
    assert all(e.score == 2.0 and e.rank == 1 for e in output[0].evidence)
    assert hybrid.generate(context, 1) == output[:1]
    with pytest.raises(ValueError, match="pool size"):
        hybrid.generate(context, 4)


def test_source_rank_is_position_after_seen_filtering(train):
    source = PopularityRetriever(train, ["A", "B", "C"])
    unfiltered = source.generate(RetrievalContext(), 3)
    after_seen = source.generate(RetrievalContext(history=("A",)), 3)
    assert [(candidate.item_id, candidate.evidence[0].rank) for candidate in unfiltered] == [
        ("A", 1),
        ("B", 2),
        ("C", 3),
    ]
    assert [(candidate.item_id, candidate.evidence[0].rank) for candidate in after_seen] == [
        ("B", 1),
        ("C", 2),
    ]


def test_hybrid_filters_untrusted_cached_pool_and_rejects_wrong_sources(train):
    source = PopularityRetriever(train, ["A", "B"])
    hybrid = HybridCandidateGenerator([source], pool_size=3)
    candidates = [
        Candidate(item, 1.0, (SourceEvidence(source.name, 1.0, i),))
        for i, item in enumerate(["A", "outside", "B"], 1)
    ]
    result = hybrid.fuse({source.name: candidates}, RetrievalContext(history=("A",)), 3)
    assert ids(result) == ["B"]
    assert result[0].evidence[0].rank == 3
    assert result[0].score == pytest.approx(1 / 63)
    assert hybrid.fuse({source.name: candidates}, RetrievalContext(history=("A",)), 1) == result[:1]
    with pytest.raises(ValueError, match="match"):
        hybrid.fuse({}, RetrievalContext(), 3)
    with pytest.raises(ValueError, match="unique"):
        HybridCandidateGenerator([source, source])
    with pytest.raises(ValueError, match="catalog"):
        HybridCandidateGenerator(
            [source, PopularityRetriever(train, ["A"], window_days=1, cutoff=5)]
        )


@pytest.mark.parametrize("score", [np.nan, np.inf, -np.inf])
def test_candidate_records_reject_nonfinite_scores(score):
    with pytest.raises(ValueError, match="finite"):
        SourceEvidence("als", score, 1)


def test_candidate_evidence_is_immutable_even_when_initialized_from_list():
    evidence = [SourceEvidence("als", 0.5, 1)]
    record = Candidate(2, 0.5, evidence)
    evidence.clear()
    assert record.item_id == "2"
    assert len(record.evidence) == 1
    with pytest.raises(ValueError, match="sequence"):
        RetrievalContext(history="item")


def test_fusion_matches_independent_rank_score_reference(train):
    global_source = PopularityRetriever(train, ["A", "B", "C"])
    recent = PopularityRetriever(train, ["A", "B", "C"], window_days=1, cutoff=5)
    hybrid = HybridCandidateGenerator([global_source, recent], pool_size=3)
    pools = {
        global_source.name: global_source.generate(RetrievalContext(), 3),
        recent.name: list(reversed(recent.generate(RetrievalContext(), 3))),
    }
    reference = {}
    for pool in pools.values():
        for record in pool:
            rank = record.evidence[0].rank
            reference[record.item_id] = reference.get(record.item_id, 0.0) + 1 / (60 + rank)
    expected = sorted(reference, key=lambda item: (-reference[item], item))[:2]
    result = hybrid.fuse(pools, RetrievalContext(), 2)
    assert ids(result) == expected
    assert [record.score for record in result] == [reference[item] for item in expected]


def test_knn_ranking_and_retrieval_share_accumulation_order(train):
    model = ItemKNNRecommender(n_neighbors=3, min_item_interactions=1, shrinkage_lambda=0)
    model.fit(train)
    # A graph whose positive float sums can reverse a lexical tie if the
    # request's history order controls accumulation.
    model._item_neighbors = {
        "A": [("Z", 0.1, 5), ("Y", 0.6, 5)],
        "B": [("Z", 0.2, 5)],
        "C": [("Z", 0.3, 5)],
    }
    for history in (["A", "B", "C"], ["C", "B", "A"], ["B", "A", "C", "A"]):
        scored = model.score_candidates(history)
        assert [item for item, _ in scored] == ["Z", "Y"]
        assert model.recommend(history, 10) == [item for item, _ in scored]
        assert scored == model.score_candidates(["A", "B", "C"])


def test_rare_history_fallback_is_attributed_only_to_popularity(train):
    model = ItemKNNRecommender(n_neighbors=3, min_item_interactions=10)
    model.fit(train)
    context = RetrievalContext("u", ("A",))
    knn = ItemKNNRetriever(model, ["A", "B", "C"])
    popularity = PopularityRetriever(train, ["A", "B", "C"])
    assert model.recommend(list(context.history), 2) == ["B", "C"]
    assert knn.generate(context, 2) == []
    hybrid = HybridCandidateGenerator([knn, popularity], pool_size=3)
    output = hybrid.generate(context, 2)
    assert ids(output) == ["B", "C"]
    assert all({entry.source for entry in item.evidence} == {popularity.name} for item in output)
