import json
import sys

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.data.rolling_provenance import sha256_file
from ecommerce_recsys.ranking.dataset import SnapshotFeatures, audit_rows, request_row
from ecommerce_recsys.retrieval.base import (
    Candidate,
    CandidateGenerator,
    RetrievalContext,
    SourceEvidence,
)
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator
from scripts import build_ranking_dataset as ranking_builder
from scripts.verify_ranking_dataset import audit_fold


def fixture_frames():
    train = pd.DataFrame(
        {
            "user_id": ["u", "u", "v", "x"],
            "item_id": ["A", "A", "A", "B"],
            "timestamp": [1, 2, 2, 2],
            "event_type": ["view", "addtocart", "view", "transaction"],
        }
    )
    catalog = pd.DataFrame({"item_id": ["A", "B"], "category_id": ["cat", "cat"]})
    return train, catalog


def test_as_of_features_use_cutoff_and_explicit_missing_source():
    train, catalog = fixture_frames()
    features = SnapshotFeatures.from_frames(train, catalog, cutoff=3)
    candidate = Candidate("B", 1 / 61, (SourceEvidence("global_popularity", 1.0, 1),))
    row = features.candidate_row(
        fold_index=1,
        context=RetrievalContext("u", ("A", "A")),
        candidate=candidate,
        rank=1,
        target_item_id="B",
    )
    assert row["label"] == 1
    assert row["user_event_count"] == 2
    assert row["user_distinct_item_count"] == 1
    assert row["user_category_event_count"] == 2
    assert row["item_transaction_count"] == 1
    assert row["user_days_since_last_event"] == 1 / 86_400_000
    assert row["als_present"] == 0
    assert row["als_rank"] == 1001
    assert row["als_score"] == 0.0
    assert row["global_popularity_rank"] == 1
    with pytest.raises(ValueError, match="unseen"):
        features.candidate_row(
            fold_index=1,
            context=RetrievalContext("u", ("A", "B")),
            candidate=candidate,
            rank=1,
            target_item_id="B",
        )


def test_future_training_event_is_rejected_and_cutoff_event_is_allowed():
    train, catalog = fixture_frames()
    SnapshotFeatures.from_frames(train, catalog, cutoff=2)
    future = pd.concat(
        [
            train,
            pd.DataFrame(
                {"user_id": ["u"], "item_id": ["B"], "timestamp": [4], "event_type": ["view"]}
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="cutoff"):
        SnapshotFeatures.from_frames(future, catalog, cutoff=3)


def test_missing_category_does_not_inherit_another_items_category():
    train, catalog = fixture_frames()
    catalog.loc[catalog["item_id"] == "B", "category_id"] = None
    features = SnapshotFeatures.from_frames(train, catalog, cutoff=3)
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    row = features.candidate_row(
        fold_index=1,
        context=RetrievalContext("u", ("A",)),
        candidate=candidate,
        rank=1,
        target_item_id="B",
    )
    assert row["category_known"] == 0
    assert row["user_category_event_count"] == 0


def test_zero_positive_request_stays_in_primary_denominator():
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    request = request_row(
        fold_index=1,
        cutoff=2,
        evaluation_cutoff=3,
        user_id="u",
        target_item_id="new",
        target_timestamp=3,
        catalog=frozenset({"A", "B"}),
        candidates=[candidate],
    )
    assert request["target_in_catalog"] == 0
    assert request["target_in_pool"] == 0
    assert audit_rows([request], [{"request_id": request["request_id"], "label": 0}]) == {
        "requests": 1,
        "candidates": 1,
        "positives": 0,
        "reachable": 0,
        "empty": 0,
    }
    reachable_miss = request_row(
        fold_index=1,
        cutoff=2,
        evaluation_cutoff=3,
        user_id="v",
        target_item_id="B",
        target_timestamp=3,
        catalog=frozenset({"A", "B"}),
        candidates=[],
    )
    assert audit_rows([reachable_miss], []) == {
        "requests": 1,
        "candidates": 0,
        "positives": 0,
        "reachable": 1,
        "empty": 1,
    }
    with pytest.raises(ValueError, match="after cutoff"):
        request_row(
            fold_index=1,
            cutoff=3,
            evaluation_cutoff=4,
            user_id="v",
            target_item_id="B",
            target_timestamp=3,
            catalog=frozenset({"A", "B"}),
            candidates=[],
        )
    with pytest.raises(ValueError, match="Duplicate"):
        request_row(
            fold_index=1,
            cutoff=2,
            evaluation_cutoff=3,
            user_id="u",
            target_item_id="B",
            target_timestamp=3,
            catalog=frozenset({"A", "B"}),
            candidates=[candidate, candidate],
        )


def test_streaming_fold_reconciles_positive_and_unreachable_requests(tmp_path, monkeypatch):
    output_dir = tmp_path
    train, catalog = fixture_frames()
    targets = pd.DataFrame({"user_id": ["u", "v"], "item_id": ["B", "new"], "timestamp": [4, 4]})

    class Hybrid:
        name = "hybrid"

        def generate(self, context, limit):
            assert limit == 1000
            return [Candidate("B", 1 / 61, (SourceEvidence("global_popularity", 1.0, 1),))]

    monkeypatch.setattr(ranking_builder, "build_sources", lambda *_: ([], [Hybrid()], {}, 0))
    row = ranking_builder.write_fold(
        index=1,
        cutoff=3,
        evaluation_cutoff=4,
        train=train,
        catalog=catalog,
        targets=targets,
        configs={},
        output_dir=output_dir,
        batch_size=1,
        reference_row={"totals": {"1000": {"hits": 1, "candidate_count": 2, "empty_requests": 0}}},
    )
    assert (row["requests"], row["candidates"], row["positives"], row["unreachable"]) == (
        2,
        2,
        1,
        1,
    )
    requests = pd.read_parquet(output_dir / "fold_01" / "requests.parquet")
    candidates = pd.read_parquet(output_dir / "fold_01" / "candidates.parquet")
    assert requests["target_in_pool"].tolist() == [1, 0]
    assert candidates["label"].tolist() == [1, 0]
    audit = audit_fold(output_dir / "fold_01", row)
    assert audit["null_feature_values"] == 0
    assert audit["absent_source_rows"]["als"] == 2
    expected = {"benchmark": "fixture"}
    artifact = {**expected, "folds": [row]}
    ranking_builder.save_checkpoint(output_dir / "quality.json", artifact)
    loaded = json.loads((output_dir / "quality.json").read_text(encoding="utf-8"))
    different_telemetry = {"folds": [{**row, "build_seconds": row["build_seconds"] + 1}]}
    assert ranking_builder.data_fingerprint(different_telemetry) == loaded["data_sha256"]
    ranking_builder.validate_checkpoint(loaded, expected, output_dir)
    with pytest.raises(ValueError, match="provenance"):
        ranking_builder.validate_checkpoint(loaded, {"benchmark": "changed"}, output_dir)
    (output_dir / "fold_01" / "candidates.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        ranking_builder.validate_checkpoint(loaded, expected, output_dir)


def test_ranking_builder_refuses_later_folds_before_reading_inputs(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build_ranking_dataset.py", "--max-fold", "5"])
    with pytest.raises(ValueError, match="development-only"):
        ranking_builder.main()


@pytest.mark.parametrize("invalid", [True, 1.0, np.int64(1), 0, 1001])
def test_candidate_rank_must_be_a_plain_integer_within_budget(invalid):
    train, catalog = fixture_frames()
    features = SnapshotFeatures.from_frames(train, catalog, 3)
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    with pytest.raises(ValueError, match="rank"):
        features.candidate_row(
            fold_index=1,
            context=RetrievalContext("u", ("A",)),
            candidate=candidate,
            rank=invalid,
            target_item_id="B",
        )


@pytest.mark.parametrize("invalid", [True, 3.9, float("nan")])
def test_cutoff_is_never_truncated(invalid):
    train, catalog = fixture_frames()
    with pytest.raises(ValueError, match="Cutoff"):
        SnapshotFeatures.from_frames(train, catalog, invalid)


def test_direct_request_and_fold_reject_target_after_evaluation_window(tmp_path, monkeypatch):
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    with pytest.raises(ValueError, match="evaluation cutoff"):
        request_row(
            fold_index=1,
            cutoff=3,
            evaluation_cutoff=4,
            user_id="u",
            target_item_id="B",
            target_timestamp=5,
            catalog=frozenset({"A", "B"}),
            candidates=[candidate],
        )
    train, catalog = fixture_frames()
    targets = pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [5]})
    monkeypatch.setattr(
        ranking_builder, "build_sources", lambda *_: pytest.fail("fit should not run")
    )
    with pytest.raises(ValueError, match="cutoff"):
        ranking_builder.write_fold(
            index=1,
            cutoff=3,
            evaluation_cutoff=4,
            train=train,
            catalog=catalog,
            targets=targets,
            configs={},
            output_dir=tmp_path,
            batch_size=1,
            reference_row={},
        )


@pytest.mark.parametrize("invalid", [2, -1, True])
def test_audit_rejects_nonbinary_labels(invalid):
    request = request_row(
        fold_index=1,
        cutoff=3,
        evaluation_cutoff=4,
        user_id="u",
        target_item_id="B",
        target_timestamp=4,
        catalog=frozenset({"A", "B"}),
        candidates=[],
    )
    with pytest.raises(ValueError, match="binary"):
        audit_rows([request], [{"request_id": request["request_id"], "label": invalid}])


def test_duplicate_catalog_rejected_before_expensive_fit(tmp_path, monkeypatch):
    train, catalog = fixture_frames()
    catalog = pd.concat([catalog, catalog.iloc[[0]]], ignore_index=True)
    targets = pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [4]})
    monkeypatch.setattr(
        ranking_builder, "build_sources", lambda *_: pytest.fail("fit should not run")
    )
    with pytest.raises(ValueError, match="duplicate"):
        ranking_builder.write_fold(
            index=1,
            cutoff=3,
            evaluation_cutoff=4,
            train=train,
            catalog=catalog,
            targets=targets,
            configs={},
            output_dir=tmp_path,
            batch_size=1,
            reference_row={},
        )


def test_real_hybrid_filters_seen_before_feature_rows():
    class Direct(CandidateGenerator):
        name = "global_popularity"

        def generate(self, context, limit):
            return self._candidates([("A", 2.0), ("B", 1.0)], context, limit)

    train, catalog = fixture_frames()
    hybrid = HybridCandidateGenerator([Direct(catalog["item_id"])], pool_size=2)
    context = RetrievalContext("u", ("A",))
    pool = hybrid.generate(context, 2)
    assert [candidate.item_id for candidate in pool] == ["B"]
    row = SnapshotFeatures.from_frames(train, catalog, 3).candidate_row(
        fold_index=1, context=context, candidate=pool[0], rank=1, target_item_id="B"
    )
    assert row["label"] == 1


def test_verifier_rejects_revisited_request_group(tmp_path, monkeypatch):
    train, catalog = fixture_frames()
    targets = pd.DataFrame(
        {"user_id": ["u", "v", "x"], "item_id": ["B", "B", "A"], "timestamp": [4, 4, 4]}
    )

    class Hybrid:
        name = "hybrid"

        def generate(self, context, limit):
            item = "A" if context.user_id == "x" else "B"
            return [Candidate(item, 1.0, (SourceEvidence("global_popularity", 1.0, 1),))]

    monkeypatch.setattr(ranking_builder, "build_sources", lambda *_: ([], [Hybrid()], {}, 0))
    row = ranking_builder.write_fold(
        index=1,
        cutoff=3,
        evaluation_cutoff=4,
        train=train,
        catalog=catalog,
        targets=targets,
        configs={},
        output_dir=tmp_path,
        batch_size=1,
        reference_row={"totals": {"1000": {"hits": 3, "candidate_count": 3, "empty_requests": 0}}},
    )
    fold_dir = tmp_path / "fold_01"
    candidates_path = fold_dir / "candidates.parquet"
    frame = pd.read_parquet(candidates_path)
    frame.loc[2, "request_id"] = frame.loc[0, "request_id"]
    frame.to_parquet(candidates_path, index=False)
    row["candidates_sha256"] = sha256_file(candidates_path)
    with pytest.raises(ValueError, match="duplicated"):
        audit_fold(fold_dir, row)


def test_nonfinite_numpy_feature_and_null_training_id_are_rejected():
    train, catalog = fixture_frames()
    features = SnapshotFeatures.from_frames(train, catalog, 3)
    features.user_events["u"] = np.float32(np.nan)
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    with pytest.raises(ValueError, match="finite"):
        features.candidate_row(
            fold_index=1,
            context=RetrievalContext("u", ("A",)),
            candidate=candidate,
            rank=1,
            target_item_id="B",
        )
    train.loc[0, "item_id"] = None
    with pytest.raises(ValueError, match="nonnull"):
        SnapshotFeatures.from_frames(train, catalog, 3)


def test_direct_request_rejects_pool_over_budget_and_null_target():
    candidate = Candidate("B", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))
    base = {
        "fold_index": 1,
        "cutoff": 3,
        "evaluation_cutoff": 4,
        "user_id": "u",
        "target_item_id": "B",
        "target_timestamp": 4,
        "catalog": frozenset({"A", "B"}),
    }
    with pytest.raises(ValueError, match="budget"):
        request_row(**base, candidates=[candidate] * 1001)
    with pytest.raises(ValueError, match="IDs"):
        request_row(**{**base, "target_item_id": None}, candidates=[])
