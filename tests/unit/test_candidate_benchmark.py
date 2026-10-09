import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.verify_candidate_artifact as artifact_verifier
from ecommerce_recsys.data.rolling_provenance import (
    fold_hashes,
    manifest_fingerprint,
    sha256_file,
)
from scripts.benchmark_candidates import (
    implementation_paths,
    main,
    save_checkpoint,
    validate_checkpoint,
)
from scripts.verify_candidate_artifact import verify


@pytest.fixture
def dataset(tmp_path):
    source = tmp_path / "interactions.parquet"
    train = pd.DataFrame(
        {
            "user_id": ["u", "v", "v"],
            "item_id": ["A", "A", "B"],
            "timestamp": [1, 2, 2],
        }
    )
    train.to_parquet(source, index=False)
    root = tmp_path / "folds"
    manifest = {
        "protocol_version": "rolling-temporal",
        "source_sha256": sha256_file(source),
        "n_windows": 10,
        "min_train_interactions": 1,
        "raw_property_sha256": {"item_properties_part1.csv": "a", "item_properties_part2.csv": "b"},
        "folds": [],
    }
    for i in range(1, 10):
        path = root / f"fold_{i:02d}"
        path.mkdir(parents=True)
        pd.DataFrame({"item_id": ["A", "B"], "category_id": ["x", "x"]}).to_parquet(
            path / "items_train.parquet", index=False
        )
        pd.DataFrame({"user_id": ["u"], "item_id": ["B"], "timestamp": [3]}).to_parquet(
            path / "warm_targets.parquet", index=False
        )
        pd.DataFrame({"user_id": ["cold"], "item_id": ["new"], "timestamp": [4]}).to_parquet(
            path / "cold_targets.parquet", index=False
        )
        manifest["folds"].append(
            {
                "fold_index": i,
                "train_cutoff": 2,
                "evaluation_cutoff": 4,
                "training_interactions": 3,
                "train_catalog_items": 2,
                "warm_target_users": 1,
                "cold_target_users": 1,
                "files_sha256": fold_hashes(path),
            }
        )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for name, config in (
        ("item_knn", {"shrinkage_lambda": 100.0}),
        ("als", {"factors": 2, "iterations": 2, "regularization": 0.01}),
    ):
        sweep = {
            "protocol_version": "rolling-temporal",
            "source_sha256": manifest["source_sha256"],
            "manifest_sha256": manifest_fingerprint(manifest),
            "model": name,
            "blind_holdout": False,
            "selected_config": config,
            "results": [
                {"phase": "final", "fold_index": i, "config": config, "evaluation_users": 1}
                for i in range(5, 10)
            ],
            "final_summary": {"user_window_targets": 5},
        }
        (tmp_path / f"{name}_sweep.json").write_text(json.dumps(sweep), encoding="utf-8")
    return source, root, manifest_path, manifest


def test_cli_actual_fit_atomic_results_resume_and_corruption(dataset, tmp_path, monkeypatch):
    source, root, manifest_path, manifest = dataset
    output = tmp_path / "candidates.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_candidates",
            "--input-path",
            str(source),
            "--fold-dir",
            str(root),
            "--manifest",
            str(manifest_path),
            "--sweep-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--max-fold",
            "1",
        ],
    )
    main()
    first = output.read_bytes()
    artifact = json.loads(first)
    assert len(artifact["results"]) == 14
    assert not output.with_suffix(".json.tmp").exists()
    assert artifact["blind_holdout"] is False
    assert artifact["post_selection_summary"] == {}
    assert artifact["development_summary"]["warm/hybrid"]["pooled_metrics"]["Recall@100"] == 1
    assert artifact["development_summary"]["cold/hybrid"]["pooled_metrics"]["Recall@100"] == 0
    with pytest.raises(ValueError, match="complete"):
        verify(artifact, manifest)
    monkeypatch.setattr(
        "scripts.benchmark_candidates.build_sources", lambda *a: pytest.fail("refitted")
    )
    main()
    assert output.read_bytes() == first
    artifact["results"][0]["reachable_targets"] = 100
    output.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        main()
    output.write_bytes(first)
    pd.DataFrame({"user_id": ["tampered"]}).to_parquet(root / "fold_01/warm_targets.parquet")
    with pytest.raises(ValueError, match="manifest"):
        main()


def test_checkpoint_refuses_policy_changes_and_partial_comparisons(tmp_path):
    expected = {"cohorts": ["warm"], "policy": {"pool": 1000}}
    manifest = {"folds": [{"fold_index": 1, "warm_target_users": 0, "train_catalog_items": 1}]}
    artifact = {**expected, "results": [], "fold_costs": []}
    save_checkpoint(tmp_path / "out.json", artifact)
    validate_checkpoint(artifact, expected, manifest)
    with pytest.raises(ValueError, match="policy"):
        validate_checkpoint(artifact, {**expected, "policy": {"pool": 500}}, manifest)
    artifact["results"] = [
        {
            "fold_index": 1,
            "generator": "als",
            "cohort": "warm",
            "evaluation_users": 0,
            "reachable_targets": 0,
            "totals": {
                str(n): {
                    "hits": 0,
                    "candidate_count": 0,
                    "empty_requests": 0,
                    "full_requests": 0,
                    "unique_items": 0,
                }
                for n in (100, 500, 1000)
            },
        }
    ]
    save_checkpoint(tmp_path / "out.json", artifact)
    with pytest.raises(ValueError, match="partial"):
        validate_checkpoint(artifact, expected, manifest)


def test_checkpoint_fingerprint_covers_cutoff_fallback_and_runner_dependencies():
    root = Path(__file__).resolve().parents[2]
    paths = {path.relative_to(root).as_posix() for path in implementation_paths(root)}
    assert {
        "src/ecommerce_recsys/data/catalog.py",
        "src/ecommerce_recsys/data/rolling_provenance.py",
        "src/ecommerce_recsys/evaluation/numeric_threads.py",
        "src/ecommerce_recsys/evaluation/rolling_artifacts.py",
        "src/ecommerce_recsys/recommendation/popularity.py",
        "src/ecommerce_recsys/recommendation/recent_popularity.py",
        "src/ecommerce_recsys/retrieval/base.py",
        "scripts/prepare_rolling_data.py",
        "scripts/benchmark_candidates.py",
        "pyproject.toml",
    }.issubset(paths)


@pytest.mark.parametrize("max_fold", ["0", "10"])
def test_cli_rejects_invalid_fold_bounds(max_fold, monkeypatch):
    monkeypatch.setattr("sys.argv", ["benchmark_candidates", "--max-fold", max_fold])
    with pytest.raises(ValueError, match="between"):
        main()


def test_published_source_proof_accepts_line_endings_and_refuses_content_changes(
    tmp_path, monkeypatch
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = scripts / "model.py"
    source.write_bytes(b"def score():\r\n    return 1\r\n")
    (tmp_path / "pyproject.toml").write_bytes(b"[project]\nname = 'example'\n")
    (tmp_path / ".gitattributes").write_bytes(b"*.py text eol=lf\n")
    monkeypatch.setattr(artifact_verifier, "__file__", str(scripts / "verifier.py"))
    snapshot = artifact_verifier.source_snapshot()
    source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
    assert artifact_verifier.source_snapshot() == snapshot
    artifact = {"implementation_sha256": "native-byte-fingerprint"}
    proof = {
        "implementation_sha256": artifact["implementation_sha256"],
        "source_snapshot": snapshot,
    }
    monkeypatch.setattr(artifact_verifier, "implementation_fingerprint", lambda: "different-native")
    monkeypatch.setattr(
        artifact_verifier,
        "source_snapshot_at_commit",
        lambda *_: artifact_verifier.source_snapshot(),
    )
    monkeypatch.setattr(artifact_verifier, "M7_SOURCE_SNAPSHOT_SHA256", snapshot["sha256"])
    monkeypatch.setattr(
        artifact_verifier, "M7_IMPLEMENTATION_SHA256", artifact["implementation_sha256"]
    )
    # Identity passes; the deliberately incomplete artifact still fails the full-data guard.
    with pytest.raises(ValueError, match="nine ordered folds"):
        verify(artifact, {"folds": []}, source_proof=proof)
    source.write_bytes(b"def score():\n    return 2\n")
    with pytest.raises(ValueError, match="source identity"):
        verify(artifact, {"folds": []}, source_proof=proof)
