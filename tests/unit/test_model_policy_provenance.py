"""Seed extraction, independent feature-audit binding and immutable verification records."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts import verify_model_policy as verifier


def test_seed_record_reads_bound_source_and_ranker_policy(tmp_path):
    path = tmp_path / "sources.py"
    path.write_text("model = MatrixFactorizationRecommender(random_state=42)\n")
    ranker = {"policy": {"negative_sampling": {"seed": 42}}}
    assert verifier.seed_record(path, ranker) == {"als_fit": 42, "ranker_negative_sampling": 42}
    path.write_text("model = MatrixFactorizationRecommender(random_state=True)\n")
    with pytest.raises(ValueError, match="seeds"):
        verifier.seed_record(path, ranker)
    path.write_text("model = MatrixFactorizationRecommender(random_state=42)\n")
    ranker["policy"]["negative_sampling"]["seed"] = 0
    with pytest.raises(ValueError, match="seeds"):
        verifier.seed_record(path, ranker)


@pytest.fixture
def feature_audit(tmp_path):
    quality = {
        "folds": [
            {
                "fold_index": index,
                "requests": 2,
                "candidates": 40,
                "positives": 1,
                "requests_sha256": str(index) * 64,
                "candidates_sha256": str(index + 4) * 64,
            }
            for index in (1, 2, 3, 4)
        ]
    }
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(json.dumps(quality))
    source = tmp_path / "verify.py"
    source.write_bytes(b"# independent scan\r\n")
    rows = [
        {**row, "null_feature_values": 0, "nonfinite_numeric_values": 0} for row in quality["folds"]
    ]
    audit = {
        "benchmark": "m10-ranking-feature-audit",
        "quality_sha256": verifier.sha256_file(quality_path),
        "verifier_sha256": verifier.normalized_sha256(source),
        "folds": rows,
    }
    return tmp_path / "audit.json", quality_path, quality, source, audit


def save_audit(path, audit):
    audit["payload_sha256"] = hashlib.sha256(
        json.dumps(audit["folds"], sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(audit))


def test_feature_audit_binds_quality_verifier_and_file_counts(feature_audit):
    path, quality_path, quality, source, audit = feature_audit
    save_audit(path, audit)
    verifier.verify_feature_audit(path, quality_path, quality, source)
    source.write_text("# changed scan implementation\n")
    with pytest.raises(ValueError, match="identity"):
        verifier.verify_feature_audit(path, quality_path, quality, source)


@pytest.mark.parametrize(
    "field,value", [("positives", 2), ("requests", True), ("null_feature_values", 1)]
)
def test_feature_audit_rejects_tampering_even_with_recomputed_payload(feature_audit, field, value):
    path, quality_path, quality, source, audit = feature_audit
    audit["folds"][0][field] = value
    save_audit(path, audit)
    with pytest.raises(ValueError, match="counts|features"):
        verifier.verify_feature_audit(path, quality_path, quality, source)


def test_feature_audit_rejects_missing_fold(feature_audit):
    path, quality_path, quality, source, audit = feature_audit
    audit["folds"].pop()
    save_audit(path, audit)
    with pytest.raises(ValueError, match="fold coverage"):
        verifier.verify_feature_audit(path, quality_path, quality, source)


def test_provenance_supplement_is_atomic_idempotent_and_refuses_replacement(tmp_path):
    path = tmp_path / "provenance.json"
    record = {"seed": 42, "artifact": "unchanged"}
    verifier.write_or_verify(path, record)
    before = path.read_bytes()
    verifier.write_or_verify(path, record)
    assert path.read_bytes() == before
    assert not path.with_suffix(".json.tmp").exists()
    with pytest.raises(ValueError, match="preserve it"):
        verifier.write_or_verify(path, {**record, "seed": 0})
    assert path.read_bytes() == before
