"""Real-source artifact parity and independent malformed-state rejection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.contract import (
    FEATURE_NAMES,
    REVIEWED_READERS,
    RuntimeCompatibilityWarning,
    component_record,
    digest,
    file_sha,
    inference_code,
    version_name,
    write_json,
)
from ecommerce_recsys.artifacts.export import export_bundle, recover_sealed_bundle
from ecommerce_recsys.artifacts.runtime import feature_matrix
from ecommerce_recsys.evaluation.model_policy import PolicyTotals
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import SnapshotFeatures
from ecommerce_recsys.retrieval.base import RetrievalContext
from scripts import benchmark_model_policy as old
from scripts.build_model_artifacts import loaded_quality, producer_reference
from scripts.learned_ranker import FEATURE_NAMES as ORIGINAL_FEATURES
from scripts.learned_ranker import PairwiseRanker
from scripts.verify_model_artifacts import verify_references


def test_component_files_are_hashed_once_per_load(bundle_path, monkeypatch):
    from collections import Counter

    from ecommerce_recsys.artifacts import contract

    calls = Counter()
    original = contract.file_sha
    pin = original(bundle_path / "model_manifest.json")

    def counted(path):
        calls[Path(path).name] += 1
        return original(path)

    monkeypatch.setattr(contract, "file_sha", counted)
    load_bundle(bundle_path, expected_manifest_sha256=pin)
    assert calls == Counter({name: 1 for name in contract.COMPONENTS | {"model_manifest.json"}})


def test_host_metadata_change_warns_but_python_patch_is_compatible(bundle_path, monkeypatch):
    from ecommerce_recsys.artifacts import contract

    current = contract.environment()
    alternative = {
        **current,
        "system": "Linux" if current["system"] != "Linux" else "Windows",
        "machine": "different-test-architecture",
        "python": "3.13.999",
    }
    expected = load_bundle(bundle_path).recommend("u0")
    monkeypatch.setattr(contract, "environment", lambda: alternative)
    with pytest.warns(RuntimeCompatibilityWarning, match="verify prediction parity"):
        loaded = load_bundle(bundle_path)
    assert loaded.recommend("u0") == expected  # Metadata simulation, not a Linux execution claim.


@pytest.mark.parametrize(
    "field", ["python", "numpy", "scipy", "pandas", "pyarrow", "implicit", "threadpoolctl"]
)
def test_incompatible_runtime_versions_fail_before_deserialization(bundle_path, field, monkeypatch):
    from ecommerce_recsys.artifacts import contract

    current = contract.environment()
    monkeypatch.setattr(
        contract,
        "environment",
        lambda: {**current, field: "3.14.0" if field == "python" else "0.0.0"},
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Incompatible runtime deserialized an array")

    monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError, match="requires"):
        load_bundle(bundle_path)


def test_reviewed_reader_requires_unchanged_prediction_implementation(bundle_path, monkeypatch):
    from ecommerce_recsys.artifacts import contract

    predecessor, expected_inference = next(iter(REVIEWED_READERS.items()))
    assert inference_code() == expected_inference
    manifest = json.loads((bundle_path / "model_manifest.json").read_text())
    manifest["runtime_code_sha256"] = predecessor
    write_json(bundle_path / "model_manifest.json", manifest)
    reseal(bundle_path)
    assert verify_references(load_bundle(bundle_path), bundle_path) == 10
    monkeypatch.setattr(contract, "inference_code", lambda: "0" * 64)
    with pytest.raises(ValueError, match="inference differs"):
        load_bundle(bundle_path)


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_json_write_failure_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch, failure):
    from ecommerce_recsys.artifacts import contract

    path = tmp_path / "record.json"
    write_json(path, {"before": 1})
    original = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("simulated persistence failure")

    if failure == "fsync":
        monkeypatch.setattr(contract.os, "fsync", fail)
    else:
        monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="persistence failure"):
        write_json(path, {"after": 2})
    assert path.read_bytes() == original
    assert not path.with_suffix(".json.tmp").exists()


def test_json_write_syncs_before_replacement(tmp_path, monkeypatch):
    from ecommerce_recsys.artifacts import contract

    calls = []
    monkeypatch.setattr(contract.os, "fsync", lambda descriptor: calls.append(descriptor))
    path = tmp_path / "record.json"
    write_json(path, {"complete": True})
    assert len(calls) == 1
    assert json.loads(path.read_text()) == {"complete": True}
    assert not path.with_suffix(".json.tmp").exists()


def test_loader_receipt_pins_original_quality_without_claiming_reevaluation(
    bundle_path, tmp_path, monkeypatch
):
    from scripts import verify_model_artifacts as verifier

    manifest = json.loads((bundle_path / "model_manifest.json").read_text())
    quality = {
        "artifact": "offline-model-bundle-validation-v1",
        "complete": True,
        "loaded_quality_matches_policy": True,
        "bundle_version": "toy-v1",
        "identity": {"manifest_sha256": file_sha(bundle_path / "model_manifest.json")},
        "components": manifest["components"],
    }
    quality["payload_sha256"] = digest(quality)
    quality_path, output = tmp_path / "quality.json", tmp_path / "loader.json"
    write_json(quality_path, quality)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_model_artifacts",
            str(bundle_path),
            "--quality-receipt",
            str(quality_path),
            "--output",
            str(output),
        ],
    )
    verifier.main()
    receipt = json.loads(output.read_text())
    assert receipt["quality_recomputed"] is False
    assert receipt["reference_requests"] == 10
    assert receipt["source_quality_receipt_sha256"] == file_sha(quality_path)
    assert receipt["payload_sha256"] == digest(
        {key: value for key, value in receipt.items() if key != "payload_sha256"}
    )
    original_bytes = output.read_bytes()
    verifier.main()
    assert output.read_bytes() == original_bytes
    quality["identity"]["manifest_sha256"] = "0" * 64
    quality.pop("payload_sha256")
    quality["payload_sha256"] = digest(quality)
    write_json(quality_path, quality)
    with pytest.raises(ValueError, match="Quality receipt"):
        verifier.main()
    assert output.read_bytes() == original_bytes


@pytest.fixture
@single_thread_benchmark
def fitted():
    # Nonempty real KNN neighbors, duplicate events, missing categories and ties.
    rows = [
        (f"u{user}", f"i{item}", 100 + item, "view")
        for user in range(9)
        for item in range(7)
        if (user + item) % 3 != 0
    ]
    rows += [("u0", "i1", 120, "addtocart"), ("u1", "i0", 121, "transaction")]
    train = pd.DataFrame(rows, columns=["user_id", "item_id", "timestamp", "event_type"])
    catalog = pd.DataFrame(
        {
            "item_id": [f"i{i}" for i in range(7)],
            "category_id": [None, "a", "a", "b", "b", "c", "c"],
        }
    )
    configs = {
        "als": {"factors": 3, "iterations": 2, "regularization": 0.01},
        "item_knn": {"shrinkage_lambda": 100.0},
    }
    sources, hybrids, _, _ = old.ranker.build_sources(train, catalog, 150, configs)
    features = SnapshotFeatures.from_frames(train, catalog, 150)
    model = PairwiseRanker(np.linspace(-0.1, 0.2, 32), np.linspace(0.5, 2, 32), 1.0, 1, True)
    predictor = old.OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=features,
        model=model,
        fold_index=9,
        categories=dict(catalog.itertuples(index=False, name=None)),
    )
    contexts = {
        str(user): RetrievalContext(str(user), tuple(frame["item_id"]))
        for user, frame in train.groupby("user_id")
    }
    references = [producer_reference(predictor, context) for context in contexts.values()]
    references.append(producer_reference(predictor, RetrievalContext()))
    snapshot = {
        "fold_index": 9,
        "cutoff": 150,
        "ranker_label_cutoff": 100,
        "users": 9,
        "items": 7,
        "events": len(train),
        "configs": configs,
        "seeds": {"als_fit": 42, "ranker_negative_sampling": 42},
    }
    return sources, features, model, snapshot, references, predictor


@pytest.fixture
def bundle_path(tmp_path, fitted):
    sources, features, model, snapshot, references, _ = fitted
    return export_bundle(
        tmp_path,
        "toy-v1",
        sources=sources,
        features=features,
        weights=model.weights,
        scales=model.scales,
        snapshot=snapshot,
        provenance={"fixture": "actual fitted toy models"},
        references=references,
    )


def reseal(path, changed=None):
    manifest = json.loads((path / "model_manifest.json").read_text())
    if changed:
        manifest["components"][changed] = component_record(path / changed)
    manifest.pop("content_sha256")
    manifest["content_sha256"] = digest(manifest)
    write_json(path / "model_manifest.json", manifest)


def test_real_source_round_trip_and_independent_package(tmp_path, bundle_path, fitted, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Inference called fit")

    from ecommerce_recsys.recommendation.item_knn import ItemKNNRecommender
    from ecommerce_recsys.recommendation.matrix_factorization import MatrixFactorizationRecommender

    monkeypatch.setattr(ItemKNNRecommender, "fit", forbidden)
    monkeypatch.setattr(MatrixFactorizationRecommender, "fit", forbidden)
    bundle = load_bundle(
        bundle_path, expected_manifest_sha256=file_sha(bundle_path / "model_manifest.json")
    )
    assert verify_references(bundle, bundle_path) == 10
    assert FEATURE_NAMES == ORIGINAL_FEATURES
    for user in bundle.users:
        result = bundle.recommend(user)
        assert result.route == "hybrid_learned"
        assert not set(result.items).intersection(bundle.context(user).history)
        assert bundle.recommend(user, k=1).items == result.items[:1]
    assert bundle.recommend("absent").items == bundle.recommend(None).items
    assert bundle.recommend("absent").route == "recent_popularity"
    assert not bundle.arrays["item_factors"].flags.writeable
    # Isolated cwd and scripts import trap; installed package is the only repo entry.
    code = """
import sys
sys.modules['scripts'] = None
from ecommerce_recsys.artifacts import load_bundle
b = load_bundle(sys.argv[1])
assert b.recommend('u0').route == 'hybrid_learned'
assert b.recommend(None).route == 'recent_popularity'
assert not any(key.startswith('scripts.') for key in sys.modules)
print('isolated-load-ok')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(bundle_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "isolated-load-ok"
    _, _, _, _, _, predictor = fitted
    pool = predictor.generators["hybrid"].generate(bundle.context("u0"), 1000)
    rows = predictor.feature_rows(pool, bundle.context("u0"))
    np.testing.assert_array_equal(
        feature_matrix(rows), old.ranker.feature_matrix(pd.DataFrame(rows))
    )


@pytest.mark.parametrize("value", [True, 0, 21, 1.0, np.int64(2), None])
def test_bad_output_limits(bundle_path, value):
    with pytest.raises(ValueError, match="Output limit"):
        load_bundle(bundle_path).recommend("u0", k=value)


@pytest.mark.parametrize("value", [True, "", " ", 1.0, [], np.int64(1)])
def test_bad_user_ids(bundle_path, value):
    with pytest.raises(ValueError, match="User ID"):
        load_bundle(bundle_path).recommend(value)


@pytest.mark.parametrize("value", ["../a", "/a", "a/b", "a\\b", "CON", "a.", "", ".."])
def test_unsafe_versions(value):
    with pytest.raises(ValueError):
        version_name(value)


@pytest.mark.parametrize("change", ["missing", "extra", "bytes", "manifest_pin", "path"])
def test_inventory_and_hashes_precede_deserialization(bundle_path, change, monkeypatch):
    if change == "missing":
        (bundle_path / "weights.npy").unlink()
    elif change == "extra":
        (bundle_path / "surprise.txt").write_text("extra")
    elif change == "bytes":
        with (bundle_path / "weights.npy").open("ab") as stream:
            stream.write(b"tamper")
    elif change == "path":
        manifest = json.loads((bundle_path / "model_manifest.json").read_text())
        manifest["components"]["../weights.npy"] = manifest["components"].pop("weights.npy")
        write_json(bundle_path / "model_manifest.json", manifest)
        reseal(bundle_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Deserialized before byte verification")

    monkeypatch.setattr(np, "load", forbidden)
    with pytest.raises(ValueError):
        load_bundle(
            bundle_path, expected_manifest_sha256="0" * 64 if change == "manifest_pin" else None
        )


@pytest.mark.parametrize(
    "change",
    [
        "shape",
        "finite",
        "scale",
        "mapping",
        "seen",
        "time",
        "affinity",
        "neighbors",
        "labels",
        "policy",
        "code",
    ],
)
def test_semantic_rejection_after_recomputed_hashes(bundle_path, change):
    changed = None
    if change in {"shape", "finite", "scale", "seen"}:
        changed = {
            "shape": "item_factors.npy",
            "finite": "user_factors.npy",
            "scale": "scales.npy",
            "seen": "seen_indices.npy",
        }[change]
        array = np.load(bundle_path / changed, allow_pickle=False)
        if change == "shape":
            array = array[:, :-1]
        else:
            array.flat[0] = {"finite": np.nan, "scale": 0, "seen": 100}.get(change, 0)
        np.save(bundle_path / changed, array, allow_pickle=False)
    elif change in {"mapping", "time", "affinity", "neighbors"}:
        changed = {
            "mapping": "users.parquet",
            "time": "items.parquet",
            "affinity": "affinities.parquet",
            "neighbors": "neighbors.parquet",
        }[change]
        frame = pd.read_parquet(bundle_path / changed)
        if change == "mapping":
            frame.loc[1, "user_id"] = frame.loc[0, "user_id"]
        elif change == "time":
            frame.loc[0, "last"] = 151
        elif change == "affinity":
            frame.loc[0, "count"] = -1
        else:
            frame.loc[0, "neighbor_id"] = "missing"
        frame.to_parquet(bundle_path / changed, index=False)
    else:
        manifest = json.loads((bundle_path / "model_manifest.json").read_text())
        if change == "labels":
            manifest["snapshot"]["ranker_label_cutoff"] = 151
        elif change == "policy":
            manifest["policy"]["candidate_budget"] = 2
        else:
            manifest["runtime_code_sha256"] = "0" * 64
        write_json(bundle_path / "model_manifest.json", manifest)
    reseal(bundle_path, changed)
    with pytest.raises(ValueError):
        load_bundle(bundle_path)


def test_safe_formats_refuse_object_arrays(bundle_path):
    np.save(bundle_path / "weights.npy", np.array([{}], dtype=object))
    manifest = json.loads((bundle_path / "model_manifest.json").read_text())
    manifest["components"]["weights.npy"]["sha256"] = file_sha(bundle_path / "weights.npy")
    manifest["components"]["weights.npy"]["bytes"] = (bundle_path / "weights.npy").stat().st_size
    write_json(bundle_path / "model_manifest.json", manifest)
    reseal(bundle_path)
    with pytest.raises(ValueError):
        load_bundle(bundle_path)


@pytest.mark.parametrize(
    "change", ["seed", "factors_bool", "lambda_nan", "schema", "null", "unsigned", "row_duplicate"]
)
def test_additional_contract_edges(bundle_path, change):
    changed = None
    if change in {"schema", "null", "row_duplicate"}:
        changed = "users.parquet"
        frame = pd.read_parquet(bundle_path / changed)
        if change == "schema":
            frame["future_target"] = "forbidden"
        elif change == "null":
            frame.loc[0, "user_id"] = None
        else:
            # Same per-user distinct counts, but repeated indices within a row.
            changed = "seen_indices.npy"
            array = np.load(bundle_path / changed)
            array[1] = array[0]
            np.save(bundle_path / changed, array, allow_pickle=False)
        if changed.endswith("parquet"):
            frame.to_parquet(bundle_path / changed, index=False)
    elif change == "unsigned":
        changed = "seen_indptr.npy"
        array = np.load(bundle_path / changed).astype(np.uint64)
        np.save(bundle_path / changed, array, allow_pickle=False)
    else:
        manifest = json.loads((bundle_path / "model_manifest.json").read_text())
        if change == "seed":
            manifest["snapshot"]["seeds"]["als_fit"] = 0
        elif change == "factors_bool":
            manifest["snapshot"]["configs"]["als"]["factors"] = True
        else:
            manifest["snapshot"]["configs"]["item_knn"]["shrinkage_lambda"] = -1
        write_json(bundle_path / "model_manifest.json", manifest)
    reseal(bundle_path, changed)
    with pytest.raises(ValueError):
        load_bundle(bundle_path)


def test_no_overwrite_sealed_resume_and_partial_failure(bundle_path, fitted):
    assert (
        recover_sealed_bundle(bundle_path.parent, "toy-v1", {"fixture": "actual fitted toy models"})
        == bundle_path
    )
    with pytest.raises(ValueError, match="provenance"):
        recover_sealed_bundle(bundle_path.parent, "toy-v1", {"fixture": "different"})
    sources, features, model, snapshot, refs, _ = fitted
    original = file_sha(bundle_path / "model_manifest.json")
    with pytest.raises(FileExistsError):
        export_bundle(
            bundle_path.parent,
            "toy-v1",
            sources=sources,
            features=features,
            weights=model.weights,
            scales=model.scales,
            snapshot=snapshot,
            provenance={},
            references=refs,
        )
    assert file_sha(bundle_path / "model_manifest.json") == original
    staging = bundle_path.parent / ".toy-v1.building"
    bundle_path.rename(staging)
    assert (
        recover_sealed_bundle(bundle_path.parent, "toy-v1", {"fixture": "actual fitted toy models"})
        == bundle_path
    )
    partial = bundle_path.parent / ".partial.building"
    partial.mkdir()
    (partial / "weights.npy").write_bytes(b"incomplete")
    with pytest.raises(ValueError):
        recover_sealed_bundle(bundle_path.parent, "partial", {})
    assert not (bundle_path.parent / "partial").exists()


def test_interrupted_export_never_publishes_or_changes_prior_version(
    bundle_path, fitted, monkeypatch
):
    sources, features, model, snapshot, refs, _ = fitted
    prior = file_sha(bundle_path / "model_manifest.json")
    original_save = np.save

    def interrupted(path, *args, **kwargs):
        if Path(path).name == "item_factors.npy":
            raise OSError("simulated disk write failure")
        return original_save(path, *args, **kwargs)

    monkeypatch.setattr(np, "save", interrupted)
    with pytest.raises(OSError, match="disk write failure"):
        export_bundle(
            bundle_path.parent,
            "interrupted",
            sources=sources,
            features=features,
            weights=model.weights,
            scales=model.scales,
            snapshot=snapshot,
            provenance={},
            references=refs,
        )
    assert not (bundle_path.parent / "interrupted").exists()
    assert (bundle_path.parent / ".interrupted.building/user_factors.npy").is_file()
    assert not (bundle_path.parent / ".interrupted.building/model_manifest.json").exists()
    assert file_sha(bundle_path / "model_manifest.json") == prior
    with pytest.raises(ValueError, match="inventory"):
        recover_sealed_bundle(bundle_path.parent, "interrupted", {})


@single_thread_benchmark
def test_empty_direct_routes_and_missing_categories_round_trip(tmp_path):
    train = pd.DataFrame(
        {
            "user_id": ["0", "0", "0"],
            "item_id": ["a", "b", "a"],
            "timestamp": [1, 2, 3],
            "event_type": ["view"] * 3,
        }
    )
    catalog = pd.DataFrame({"item_id": ["a", "b"], "category_id": [None, None]})
    cutoff = 31 * 86_400_000  # No recent items; the known user has seen the entire catalog.
    configs = {
        "als": {"factors": 3, "iterations": 2, "regularization": 0.01},
        "item_knn": {"shrinkage_lambda": 100.0},
    }
    sources, hybrids, _, _ = old.ranker.build_sources(train, catalog, cutoff, configs)
    features = SnapshotFeatures.from_frames(train, catalog, cutoff)
    model = PairwiseRanker(np.zeros(32), np.ones(32), 1.0, 1, True)
    predictor = old.OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=features,
        model=model,
        fold_index=9,
        categories={"a": None, "b": None},
    )
    references = [
        producer_reference(predictor, context)
        for context in (
            RetrievalContext("0", ("a", "b", "a")),
            RetrievalContext(),
        )
    ]
    path = export_bundle(
        tmp_path,
        "empty-v1",
        sources=sources,
        features=features,
        weights=model.weights,
        scales=model.scales,
        snapshot={
            "fold_index": 9,
            "cutoff": cutoff,
            "ranker_label_cutoff": 1,
            "users": 1,
            "items": 2,
            "events": 3,
            "configs": configs,
            "seeds": {"als_fit": 42, "ranker_negative_sampling": 42},
        },
        provenance={"fixture": "all seen and no recent items"},
        references=references,
    )
    bundle = load_bundle(path)
    assert verify_references(bundle, path) == 2
    assert bundle.recommend(0).items == ()
    assert bundle.recommend(0).route == "hybrid_learned"
    assert bundle.recommend(None).items == ()
    assert bundle.recommend(None).route == "recent_popularity"


def test_checkpoint_resume_rejects_drift_and_keeps_zero_hits(tmp_path, bundle_path):
    bundle = load_bundle(bundle_path)
    targets = {
        "warm": pd.DataFrame({"user_id": ["u0", "u1"], "item_id": ["never", "never"]}),
        "cold": pd.DataFrame({"item_id": ["never", "i1"]}),
    }
    categories = {item: bundle.features.categories.get(item) for item in bundle.items}
    totals = PolicyTotals(frozenset(bundle.items), categories)
    for row in targets["warm"].itertuples(index=False):
        trace = bundle.trace(row.user_id)
        totals.add(trace["pool"], trace["output"], row.item_id)
    cold = PolicyTotals(totals.catalog, categories)
    from collections import Counter

    trace = bundle.trace(None)
    cold.add_shared(trace["pool"], trace["output"], Counter(targets["cold"]["item_id"]))
    expected = {
        "warm": {"hybrid_learned": totals.output()},
        "cold": {"recent_popularity": cold.output()},
    }
    checkpoint = tmp_path / "checkpoint.json"
    first = loaded_quality(bundle, targets, expected, checkpoint, {"bundle": "toy"})
    second = loaded_quality(bundle, targets, expected, checkpoint, {"bundle": "toy"})
    assert first["quality"] == second["quality"]
    assert first["quality"]["warm"]["requests"] == 2
    assert first["quality"]["warm"]["hits"]["20"] == 0
    with pytest.raises(ValueError, match="checkpoint"):
        loaded_quality(bundle, targets, expected, checkpoint, {"bundle": "other"})


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires a Windows privilege.")
def test_symlink_component_rejected(bundle_path, tmp_path):
    outside = tmp_path / "outside.npy"
    (bundle_path / "weights.npy").rename(outside)
    (bundle_path / "weights.npy").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        load_bundle(bundle_path)
