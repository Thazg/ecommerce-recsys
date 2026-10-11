"""Regression checks for same-pool pairwise ranking and temporal selection."""

from argparse import Namespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import benchmark_ranker as runner
from scripts.learned_ranker import (
    FEATURE_NAMES,
    PairwiseRanker,
    RankingTotals,
    feature_matrix,
    iter_candidate_groups,
    positive_rank,
    sample_pair_indices,
    sample_training_pairs,
)


def _feature_row(**overrides):
    row = {name: 0.0 for name in FEATURE_NAMES}
    for name in FEATURE_NAMES:
        if name == "retrieval_rank" or name.endswith("_rank"):
            row[name] = 1.0
    row.update(overrides)
    return row


def test_features_exclude_identifiers_and_labels_and_reject_nonfinite():
    assert not {"label", "fold_index", "item_id", "request_id"}.intersection(FEATURE_NAMES)
    frame = pd.DataFrame([_feature_row(item_event_count=9, als_score=-3.0)])
    frame["label"] = 1
    first = feature_matrix(frame)
    frame["label"] = 0
    assert np.array_equal(first, feature_matrix(frame))
    assert first[0, FEATURE_NAMES.index("item_event_count")] == pytest.approx(np.log1p(9))
    assert first[0, FEATURE_NAMES.index("als_score")] == pytest.approx(-np.log1p(3))
    assert first[0, FEATURE_NAMES.index("retrieval_rank")] == pytest.approx(1 / 61)
    frame["als_score"] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        feature_matrix(frame)


def test_sampler_is_request_stable_and_excludes_zero_positive():
    labels = np.zeros(1000, dtype=np.int8)
    labels[7] = 1
    first = sample_pair_indices("request-a", labels)
    assert first is not None
    positive, negatives = first
    assert positive == 7
    assert len(negatives) == 100
    assert 7 not in negatives
    assert np.array_equal(negatives, sample_pair_indices("request-a", labels)[1])
    assert sample_pair_indices("request-a", np.zeros(5, dtype=np.int8)) is None
    with pytest.raises(ValueError, match="multiple"):
        sample_pair_indices("request-a", np.array([1, 1], dtype=np.int8))


def test_group_stream_survives_batch_split_and_pair_fit(tmp_path):
    rows = []
    for request, positive in (("a", 2), ("b", 0), ("c", None)):
        for rank in range(1, 5):
            rows.append(
                {
                    "request_id": request,
                    "item_id": f"{request}-{rank}",
                    "label": int(rank == positive),
                    **_feature_row(retrieval_rank=rank, item_event_count=rank),
                }
            )
    path = tmp_path / "candidates.parquet"
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows)), path)
    groups = list(iter_candidate_groups(path, batch_size=3))
    assert [(key, len(frame)) for key, frame in groups] == [("a", 4), ("b", 4), ("c", 4)]
    pairs = sample_training_pairs(path, batch_size=3)
    assert pairs.requests == 3
    assert pairs.positive_requests == 1
    assert pairs.zero_positive_requests == 2
    assert pairs.pairs == 3
    model = PairwiseRanker.fit(pairs.differences, alpha=0.01, max_iterations=20)
    assert np.isfinite(model.score(feature_matrix(groups[0][1]))).all()
    repeated = PairwiseRanker.fit(pairs.differences, alpha=0.01, max_iterations=20)
    assert np.array_equal(model.weights, repeated.weights)


def test_positive_rank_uses_item_id_tie_break_and_all_request_denominator():
    scores = np.array([0.5, 0.5, 0.1])
    items = np.array(["z", "a", "q"])
    labels = np.array([1, 0, 0])
    assert positive_rank(scores, items, labels) == 2
    totals = RankingTotals()
    totals.add(pool_size=3, rrf_rank=1, learned_rank=2)
    totals.add(pool_size=0, rrf_rank=None, learned_rank=None)
    result = totals.as_dict()
    assert result["requests"] == 2
    assert result["target_in_pool"] == 1
    assert result["learned"]["HR@5"] == 0.5
    assert result["learned"]["conditional"]["HR@5"] == 1.0
    assert result["learned"]["MRR@5"] == 0.25


def test_parquet_evaluation_keeps_same_pool_and_zero_positive_requests(tmp_path):
    fold_dir = tmp_path / "fold_02"
    fold_dir.mkdir()
    pd.DataFrame(
        [
            {"request_id": "a", "target_item_id": "z", "pool_size": 2, "target_in_pool": 1},
            {"request_id": "b", "target_item_id": "missing", "pool_size": 2, "target_in_pool": 0},
            {"request_id": "c", "target_item_id": "missing", "pool_size": 0, "target_in_pool": 0},
        ]
    ).to_parquet(fold_dir / "requests.parquet")
    candidate_rows = []
    for request, items in (("a", ("z", "a")), ("b", ("x", "y"))):
        for rank, item in enumerate(items, start=1):
            candidate_rows.append(
                {
                    "request_id": request,
                    "item_id": item,
                    "label": int(request == "a" and item == "z"),
                    **_feature_row(retrieval_rank=rank),
                }
            )
    pd.DataFrame(candidate_rows).to_parquet(fold_dir / "candidates.parquet")
    model = PairwiseRanker(
        weights=np.zeros(len(FEATURE_NAMES)),
        scales=np.ones(len(FEATURE_NAMES)),
        alpha=0.01,
        iterations=0,
        converged=True,
    )
    result = runner.evaluate_parquet_fold(
        tmp_path, model, {"fold_index": 2, "requests": 3, "candidates": 4, "positives": 1}
    )
    assert result["requests"] == 3
    assert result["candidate_recall@1000"] == pytest.approx(1 / 3)
    assert result["rrf"]["MRR@5"] == pytest.approx(1 / 3)
    assert result["learned"]["MRR@5"] == pytest.approx(1 / 6)
    assert result["learned"]["conditional"]["MRR@5"] == pytest.approx(1 / 2)


def test_checkpoint_tamper_is_rejected(tmp_path):
    path = tmp_path / "development.json"
    runner.write_json_atomic(path, {"benchmark": "example", "folds": []})
    assert not path.with_suffix(".json.tmp").exists()
    assert runner.read_validated_artifact(path, {"benchmark": "example"})["folds"] == []
    payload = path.read_text(encoding="utf-8").replace('"folds": []', '"folds": [1]')
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        runner.read_validated_artifact(path, {"benchmark": "example"})


def test_selection_requires_complete_development_and_uses_locked_rule():
    def row(index, scores):
        return {
            "fold_index": index,
            "requests": 10,
            "configs": {
                str(alpha): {"metrics": {"learned": {"hits": {"20": hits}, "NDCG@20": ndcg}}}
                for alpha, (hits, ndcg) in scores.items()
            },
        }

    scores = {0.0001: (2, 0.1), 0.001: (2, 0.2), 0.01: (2, 0.2)}
    rows = [row(index, scores) for index in (2, 3, 4)]
    assert runner.select_alpha(rows) == 0.01
    with pytest.raises(ValueError, match="complete development"):
        runner.select_alpha(rows[:2])


def test_diagnostic_refuses_incomplete_development_and_unbound_lock(tmp_path):
    development_path = tmp_path / "development.json"
    lock_path = tmp_path / "lock.json"
    args = Namespace(development_artifact=development_path, selection_lock=lock_path)
    expected = {"benchmark": "pairwise-ranker-development-v1", "code_sha256": "fixed"}
    runner.write_json_atomic(development_path, {**expected, "folds": [], "complete": False})
    with pytest.raises(ValueError, match="complete before diagnostic"):
        runner.require_development_and_lock(args, {"code_sha256": "fixed"})

    scores = {alpha: (1, 0.1) for alpha in runner.POLICY["alpha_grid"]}
    rows = [
        {
            "fold_index": index,
            "requests": 10,
            "configs": {
                str(alpha): {"metrics": {"learned": {"hits": {"20": hits}, "NDCG@20": ndcg}}}
                for alpha, (hits, ndcg) in scores.items()
            },
        }
        for index in (2, 3, 4)
    ]
    runner.write_json_atomic(
        development_path,
        {**expected, "folds": rows, "complete": True, "selected_alpha": 0.01},
    )
    with pytest.raises(FileNotFoundError):
        runner.require_development_and_lock(args, {"code_sha256": "fixed"})

    runner.write_json_atomic(
        lock_path,
        {
            "benchmark": "pairwise-ranker-selection-lock-v1",
            "code_sha256": "fixed",
            "development_artifact_sha256": runner.sha256_file(development_path),
            "selected_alpha": 0.01,
        },
    )
    runner.require_development_and_lock(args, {"code_sha256": "fixed"})
    runner.write_json_atomic(lock_path, {"benchmark": "wrong"})
    with pytest.raises(ValueError, match="provenance or policy"):
        runner.require_development_and_lock(args, {"code_sha256": "fixed"})
