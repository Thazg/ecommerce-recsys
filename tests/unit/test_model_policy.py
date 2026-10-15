"""Complete-policy denominators, transfer behavior, selection and resume guards."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.evaluation.model_policy import (
    COLD_POLICIES,
    WARM_POLICIES,
    PolicyTotals,
    pooled_results,
    select_routes,
    validate_result,
)
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import SnapshotFeatures
from ecommerce_recsys.retrieval.base import Candidate, RetrievalContext, SourceEvidence
from scripts import benchmark_model_policy as runner
from scripts.learned_ranker import FEATURE_NAMES, PairwiseRanker


def _totals(hit_count=1, misses=1):
    ids = [f"i{index:02d}" for index in range(25)]
    total = PolicyTotals(
        frozenset(ids), {item: "x" if index < 10 else None for index, item in enumerate(ids)}
    )
    total.add_shared(ids, ids[:20], Counter({ids[1]: hit_count, "unreachable": misses}))
    return total.output()


def _selection_rows():
    return [
        {
            "fold_index": index,
            "warm": {spec.name: _totals() for spec in WARM_POLICIES},
            "cold": {spec.name: _totals() for spec in COLD_POLICIES},
        }
        for index in (2, 3, 4)
    ]


def test_metrics_keep_unreachable_misses_and_use_actual_rank():
    result = _totals()
    validate_result(result, requests=2, catalog_size=25)
    assert result["candidate_recall@1000"] == 0.5
    assert result["reachable_candidate_recall@1000"] == 1.0
    assert result["HR@20"] == 0.5
    assert result["MRR@20"] == 0.25
    assert result["NDCG@20"] == 1 / (2 * np.log2(3))
    assert result["distinct_known_category_slots@20"] == 1 / 20
    assert result["item_coverage@20"] == 20 / 25


def test_shared_cold_counts_equal_every_request_and_zero_cohort():
    catalog = frozenset(("a", "b", "c"))
    categories = {"a": "x", "b": "y", "c": None}
    shared = PolicyTotals(catalog, categories)
    shared.add_shared(["a", "b"], ["b", "a"], Counter({"a": 3, "c": 2, "unknown": 4}))
    serial = PolicyTotals(catalog, categories)
    for target in ["a"] * 3 + ["c"] * 2 + ["unknown"] * 4:
        serial.add(["a", "b"], ["b", "a"], target)
    shared_result, serial_result = shared.output(), serial.output()
    for key, value in shared_result.items():
        assert (
            value == pytest.approx(serial_result[key])
            if isinstance(value, (float, dict))
            else value == serial_result[key]
        )
    empty = PolicyTotals(catalog, categories)
    empty.add_shared(["a"], ["a"], Counter())
    validate_result(empty.output(), requests=0, catalog_size=3)
    assert empty.output()["item_coverage@20"] == 0


def test_empty_pool_denominator_and_invalid_outputs():
    total = PolicyTotals(frozenset(("a",)), {"a": None})
    total.add([], [], "a")
    result = total.output()
    validate_result(result, requests=1, catalog_size=1)
    assert result["HR@20"] == 0
    assert result["empty_output_rate"] == 1
    for pool, output, target, seen in (
        (["a", "a"], ["a"], "b", frozenset()),
        (["a"], ["a"], "b", frozenset(("a",))),
        (["a"], [], "b", frozenset()),
        (["a"], ["b"], "b", frozenset()),
        (["a"], ["a"], "a", frozenset(("a",))),
    ):
        with pytest.raises(ValueError, match="contract"):
            total.add(pool, output, target, seen)


@pytest.mark.parametrize("value", [True, 1.0, np.int64(1), -1])
def test_shared_target_weights_are_plain_positive_integer_counts(value):
    total = PolicyTotals(frozenset(("a",)), {"a": "x"})
    with pytest.raises(ValueError, match="contract"):
        total.add_shared(["a"], ["a"], Counter({"a": value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_in_pool", 3),
        ("requests", True),
        ("candidate_count", 0),
        ("HR@20", 0.9),
        ("short_outputs", 0),
    ],
)
def test_result_validation_rejects_impossible_or_modified_counts(field, value):
    result = _totals()
    if field == "short_outputs":
        result["recommendation_slots"] = 2
    result[field] = value
    with pytest.raises(ValueError):
        validate_result(result, requests=2, catalog_size=25)


def test_selection_pools_requests_and_uses_fixed_cost_tie_break():
    rows = _selection_rows()
    for row in rows:
        row["warm"]["hybrid_learned"] = _totals(3, 1)
        row["warm"]["no_als_learned_transfer"] = _totals(3, 1)
    assert select_routes(rows) == {"warm": "no_als_learned_transfer", "cold": "global_popularity"}
    pooled = pooled_results(rows, "warm", "no_als_learned_transfer")
    assert pooled["requests"] == 12 and pooled["hits"]["20"] == 9
    assert pooled["HR@20"] == 0.75
    assert "item_coverage@20" not in pooled and "unique_items" not in pooled
    rows[0]["warm"]["hybrid_learned"] = _totals(4, 1)
    assert select_routes(rows)["warm"] == "hybrid_learned"


def test_selection_uses_ndcg_then_bonus_and_rejects_later_or_partial_folds():
    rows = _selection_rows()
    for row in rows:
        for name in ("hybrid_learned", "hybrid_category"):
            row["warm"][name] = _totals(3, 1)
    assert select_routes(rows)["warm"] == "hybrid_learned"
    for row in rows:
        row["warm"]["hybrid_category"]["discounted_sum"]["20"] += 0.01
    assert select_routes(rows)["warm"] == "hybrid_category"
    with pytest.raises(ValueError, match="complete"):
        select_routes(rows[:2])
    rows[0]["fold_index"] = 5
    with pytest.raises(ValueError, match="complete"):
        select_routes(rows)


@single_thread_benchmark
def test_real_sources_transfer_no_als_and_cold_route_behavior():
    events = []
    for user, items in (("u", "AB"), ("v", "ACDE"), ("w", "BCDF"), ("z", "EFAB")):
        events.extend((user, item, 1, "view") for item in items for _ in range(5))
    train = pd.DataFrame(events, columns=["user_id", "item_id", "timestamp", "event_type"])
    catalog = pd.DataFrame(
        {"item_id": list("ABCDEF"), "category_id": ["x", "x", "y", "y", None, "z"]}
    )
    sources, hybrids, _, _ = runner.ranker.build_sources(
        train,
        catalog,
        2,
        {
            "item_knn": {"shrinkage_lambda": 100},
            "als": {"factors": 2, "iterations": 2, "regularization": 0.01},
        },
    )
    model = PairwiseRanker(np.zeros(len(FEATURE_NAMES)), np.ones(len(FEATURE_NAMES)), 0.01, 1, True)
    predictor = runner.OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=SnapshotFeatures.from_frames(train, catalog, 2),
        model=model,
        fold_index=2,
        categories=runner.diversity.category_map(catalog, expected_items=6),
    )
    context = RetrievalContext("u", ("A", "B", "A"))
    shared = predictor.quality_outputs(context)
    for spec in WARM_POLICIES:
        assert predictor.predict(spec, context) == shared[spec.name]
        pool, output = shared[spec.name]
        assert set(output).issubset(pool) and not set(pool).intersection(context.history)
        assert len(set(pool)) == len(pool)
    transferred = predictor.generators["hybrid_without_als"].generate(context, 1000)
    assert all(
        "als" not in {entry.source for entry in candidate.evidence} for candidate in transferred
    )
    full = predictor.generators["hybrid"].generate(context, 1000)
    cache = {row["item_id"]: row for row in predictor.feature_rows(full[:-1], context)}
    changed_pool = list(reversed(transferred))
    cached_rows = predictor.feature_rows(changed_pool, context, cache)
    independent_rows = predictor.feature_rows(changed_pool, context)
    assert np.array_equal(
        runner.feature_matrix(pd.DataFrame(cached_rows)),
        runner.feature_matrix(pd.DataFrame(independent_rows)),
    )
    if cache:
        with pytest.raises(ValueError, match="different request"):
            predictor.feature_rows(full[:-1], RetrievalContext("v", ("A",)), cache)
    observed = []
    original_score = model.score

    # Capture the transformed predictor matrix to check absent ALS evidence.
    class CaptureModel:
        def score(self, features):
            observed.append(features)
            return original_score(features)

    predictor.model = CaptureModel()
    predictor.scores(transferred, context)
    assert (observed[0][:, FEATURE_NAMES.index("als_present")] == 0).all()
    cold = RetrievalContext()
    for name in ("item_knn", "als", "category_popularity"):
        assert predictor.sources[name].generate(cold, 1000) == []
    for spec in COLD_POLICIES:
        pool, output = predictor.predict(spec, cold)
        assert pool and output and set(output).issubset(pool)
    with pytest.raises(ValueError, match="warm"):
        predictor.scores(transferred, cold)
    with pytest.raises(ValueError, match="seen"):
        predictor.validate_pool(
            [Candidate("A", 1.0, (SourceEvidence("global_popularity", 1.0, 1),))], context
        )


def test_latency_sample_is_stable_and_policy_calls_reconcile():
    contexts = {user: RetrievalContext(user, ("seen",)) for user in ("b", "a", "c")}
    assert runner.latency_sample(contexts, 2) == runner.latency_sample(
        dict(reversed(list(contexts.items()))), 2
    )

    class Predictor:
        def predict(self, spec, context):
            return ["a"], ["a"]

    expected = {
        user: {spec.name: runner.digest([["a"], ["a"]]) for spec in COLD_POLICIES}
        for user in contexts
    }
    result = runner.measure_latency(
        Predictor(), list(contexts.values()), COLD_POLICIES, repetitions=2, expected=expected
    )
    assert all(row["latency_samples"] == 6 for row in result.values())
    expected["a"]["global_popularity"] = "bad"
    with pytest.raises(ValueError, match="differs"):
        runner.measure_latency(
            Predictor(), list(contexts.values()), COLD_POLICIES, repetitions=1, expected=expected
        )


def test_atomic_checksum_and_timing_independent_result_identity(tmp_path):
    path = tmp_path / "checkpoint.json"
    row = {
        "fold_index": 2,
        "cutoff": 2,
        "ranker_training_folds": [1],
        "model": {},
        "warm": {},
        "cold": {},
        "costs": {"seconds": 1.0},
    }
    artifact = {"benchmark": "pilot", "folds": [row], "complete": False}
    runner.write_artifact(path, artifact)
    initial = runner.read_artifact(path, {"benchmark": "pilot"})
    row["costs"]["seconds"] = 2.0
    runner.write_artifact(path, artifact)
    changed = runner.read_artifact(path, {"benchmark": "pilot"})
    assert changed["result_sha256"] == initial["result_sha256"]
    assert changed["payload_sha256"] != initial["payload_sha256"]
    assert not path.with_suffix(".json.tmp").exists()
    with pytest.raises(ValueError, match="provenance"):
        runner.read_artifact(path, {"benchmark": "different"})
    changed["folds"][0]["cutoff"] = 3
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        runner.read_artifact(path, {"benchmark": "pilot"})


def test_lock_pins_published_model_files_without_reading_scores(tmp_path):
    ranker_path = tmp_path / "ranker.json"
    diversity_path = tmp_path / "diversity.json"
    ranker_path.write_text("opaque model bytes", encoding="utf-8")
    diversity_path.write_text("opaque comparison bytes", encoding="utf-8")
    args = argparse.Namespace(ranker_diagnostic=ranker_path, diversity_diagnostic=diversity_path)
    expected = runner.published_artifact_hashes(args)
    lock_path = tmp_path / "lock.json"
    runner.write_artifact(lock_path, {"benchmark": "lock", **expected})
    runner.read_artifact(lock_path, expected)
    ranker_path.write_text("changed model bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        runner.read_artifact(lock_path, runner.published_artifact_hashes(args))


def test_completion_and_diagnostic_guard_precede_input_reads(monkeypatch):
    with pytest.raises(ValueError, match="max fold"):
        runner.run(argparse.Namespace(phase="diagnostic", max_fold=4))
    with pytest.raises(ValueError, match="completion"):
        runner.validate_completion({"folds": [], "complete": True}, {"folds": []}, "diagnostic")
    with pytest.raises(ValueError, match="invalid phase"):
        runner.validate_completion(
            {"folds": [{"fold_index": 6}], "complete": False}, {"folds": []}, "diagnostic"
        )
    with pytest.raises(ValueError, match="completion"):
        runner.validate_completion({"folds": [], "complete": 0}, {"folds": []}, "development")


def test_missing_lock_blocks_diagnostic_and_incomplete_development(tmp_path, monkeypatch):
    args = argparse.Namespace(
        phase="diagnostic",
        development_artifact=tmp_path / "dev.json",
        selection_lock=tmp_path / "lock.json",
    )
    monkeypatch.setattr(runner, "validate_completion", lambda *args: None)
    monkeypatch.setattr(runner, "read_artifact", lambda *args: {"complete": False})
    with pytest.raises(ValueError, match="all development"):
        runner.require_lock(args, {}, {})
    rows = _selection_rows()
    monkeypatch.setattr(
        runner,
        "read_artifact",
        lambda *args: {"complete": True, "folds": rows, "result_sha256": "x"},
    )
    args.development_artifact.write_text("{}", encoding="utf-8")
    # A diagnostic phase must not create a missing lock.
    calls = []
    monkeypatch.setattr(runner, "write_artifact", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="explicitly created"):
        runner.require_lock(args, {}, {})
    assert calls == []


@pytest.mark.parametrize("cutoff", [True, 3.9, float("nan"), np.int64(3)])
def test_manifest_rejects_noninteger_cutoff(cutoff):
    fold = {
        "fold_index": 1,
        "train_cutoff": cutoff,
        "evaluation_cutoff": 5,
        "training_interactions": 2,
        "train_catalog_items": 2,
        "warm_target_users": 1,
        "cold_target_users": 1,
    }
    with pytest.raises(ValueError, match="plain integers"):
        runner.validate_boundaries({"folds": [fold]})


@pytest.mark.parametrize("target_time", [1, 5])
def test_target_bounds_reject_before_model_fit(tmp_path, target_time):
    train = pd.DataFrame(
        {
            "user_id": ["u", "v"],
            "item_id": ["A", "B"],
            "timestamp": [1, 1],
            "event_type": ["view", "view"],
        }
    )
    folder = tmp_path / "fold_02"
    folder.mkdir()
    pd.DataFrame({"item_id": ["A", "B"], "category_id": ["x", "y"]}).to_parquet(
        folder / "items_train.parquet"
    )
    pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [target_time]}).to_parquet(
        folder / "warm_targets.parquet"
    )
    pd.DataFrame({"user_id": ["c"], "item_id": ["A"], "timestamp": [3]}).to_parquet(
        folder / "cold_targets.parquet"
    )
    fold = {
        "fold_index": 2,
        "train_cutoff": 2,
        "evaluation_cutoff": 4,
        "training_interactions": 2,
        "train_catalog_items": 2,
        "warm_target_users": 1,
        "cold_target_users": 1,
    }
    with pytest.raises(ValueError, match="time boundary"):
        runner.evaluate_fold(
            argparse.Namespace(fold_dir=tmp_path),
            fold=fold,
            interactions=train,
            configs={},
            model=None,
            training_folds=[1],
            ranker_metrics={},
            diversity_metrics={},
            reference_rows={},
            training_cost={},
        )


def test_fingerprint_uses_historical_scope_instead_of_growing_package_hash(monkeypatch):
    monkeypatch.setattr(runner.diversity, "code_fingerprint", lambda: "upstream-a")
    first = runner.code_fingerprint()
    monkeypatch.setattr(runner.ranker, "code_fingerprint", lambda: "unrelated-future-module")
    assert runner.code_fingerprint() == first
    monkeypatch.setattr(runner.diversity, "code_fingerprint", lambda: "upstream-b")
    assert runner.code_fingerprint() != first


@pytest.mark.parametrize(
    "relative",
    ["scripts/learned_ranker.py", "scripts/benchmark_candidates.py", "scripts/benchmark_ranker.py"],
)
def test_transitive_fingerprint_rejects_changed_ranker_or_source(relative, monkeypatch, tmp_path):
    # Exercise real hashing, with a tiny Git tree so shallow CI needs no old commits.
    def git(args, **kwargs):
        return SimpleNamespace(
            stdout="src/ecommerce_recsys/retrieval/base.py\n" if args[1] == "ls-tree" else "",
            returncode=0,
        )

    monkeypatch.setattr(runner.diversity.subprocess, "run", git)
    before = runner.code_fingerprint()
    path = tmp_path / "artifact.json"
    runner.write_artifact(path, {"code_sha256": before, "folds": []})
    changed_path = Path(runner.__file__).resolve().parents[1] / relative
    original_read = Path.read_bytes

    def read_bytes(path):
        data = original_read(path)
        return data + b"\n# changed implementation\n" if path == changed_path else data

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    after = runner.code_fingerprint()
    assert after != before
    with pytest.raises(ValueError, match="provenance"):
        runner.read_artifact(path, {"code_sha256": after})


def test_fingerprint_refuses_modified_historical_source(monkeypatch):
    def git(args, **kwargs):
        return SimpleNamespace(
            stdout="src/ecommerce_recsys/retrieval/base.py\n", returncode=int(args[1] == "diff")
        )

    monkeypatch.setattr(runner.diversity.subprocess, "run", git)
    with pytest.raises(ValueError, match="Published M10/M11 source changed"):
        runner.code_fingerprint()
