import json

import pandas as pd
import pytest

from ecommerce_recsys.data.rolling_provenance import FOLD_FILES, manifest_fingerprint
from ecommerce_recsys.evaluation.rolling_artifacts import require_completed_sweeps
from scripts.benchmark_rolling import main as benchmark_main
from scripts.benchmark_rolling import summarize
from scripts.benchmark_rolling_cold import _metrics, _summarize
from scripts.benchmark_rolling_cold import main as cold_main
from scripts.sweep_rolling import _score, _validate_final_checkpoint


def test_pooling_weights_folds_by_user_window_count():
    rows = [
        {"model": "a", "fold_index": 1, "evaluation_users": 1, "metrics": {"HR@20": 1.0}},
        {"model": "a", "fold_index": 2, "evaluation_users": 3, "metrics": {"HR@20": 0.0}},
    ]
    assert summarize(rows)["a"]["pooled_metrics"]["HR@20"] == 0.25


def test_sweep_selection_uses_only_first_four_folds():
    config = {"shrinkage_lambda": 10.0}
    rows = [
        {
            "config": config,
            "fold_index": index,
            "evaluation_users": 10,
            "metrics": {"HR@20": 0.1, "NDCG@20": 0.05},
        }
        for index in range(1, 5)
    ]
    rows.append(
        {
            "config": config,
            "fold_index": 5,
            "evaluation_users": 1000,
            "metrics": {"HR@20": 1.0, "NDCG@20": 1.0},
        }
    )
    assert _score(rows, config) == (0.1, 0.05)


def test_cold_vectorized_metrics_include_unreachable_targets():
    metrics = _metrics(pd.Series(["A", "B", "new"]), ["B", "A"])
    assert metrics["HR@5"] == 0.666667
    assert metrics["MRR@5"] == 0.5


def test_cold_empty_fold_has_zero_metrics_and_no_division():
    metrics = _metrics(pd.Series([], dtype=str), [])
    assert all(value == 0.0 for value in metrics.values())
    rows = [
        {"model": "global_popularity", "evaluation_users": 0, "metrics": metrics},
    ]
    assert _summarize(rows)["global_popularity"]["pooled_metrics"]["HR@20"] == 0.0


def test_cold_runner_resumes_empty_selection_fold_without_sweeps(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol_version": "rolling-temporal",
                "source_sha256": "test-source",
                "n_windows": 10,
                "min_train_interactions": 1,
                "raw_property_sha256": {
                    "item_properties_part1.csv": "x",
                    "item_properties_part2.csv": "y",
                },
                "folds": [
                    {
                        "fold_index": i,
                        "train_cutoff": 1,
                        "cold_target_users": 0,
                        "files_sha256": {name: "x" for name in FOLD_FILES},
                    }
                    for i in range(1, 10)
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "cold.json"
    monkeypatch.setattr("scripts.benchmark_rolling_cold.sha256_file", lambda _: "test-source")
    monkeypatch.setattr("scripts.benchmark_rolling_cold.verify_fold_files", lambda *a: None)

    def read_parquet(path, **kwargs):
        name = str(path)
        if name.endswith("cold_targets.parquet"):
            return pd.DataFrame({"item_id": pd.Series([], dtype=str)})
        if name.endswith("items_train.parquet"):
            return pd.DataFrame({"item_id": ["A"]})
        return pd.DataFrame({"timestamp": [1], "item_id": ["A"]})

    monkeypatch.setattr("scripts.benchmark_rolling_cold.pd.read_parquet", read_parquet)
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_rolling_cold",
            "--input-path",
            str(tmp_path / "source.parquet"),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--max-fold",
            "4",
        ],
    )
    cold_main()
    cold_main()
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert len(artifact["results"]) == 8
    assert artifact["known_item_rate_by_fold"] == [
        {"fold_index": index, "rate": None} for index in range(1, 5)
    ]


def test_cold_runner_preserves_completed_model_after_failure(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol_version": "rolling-temporal",
                "source_sha256": "test-source",
                "n_windows": 10,
                "min_train_interactions": 1,
                "raw_property_sha256": {
                    "item_properties_part1.csv": "x",
                    "item_properties_part2.csv": "y",
                },
                "folds": [
                    {
                        "fold_index": i,
                        "train_cutoff": 1,
                        "cold_target_users": 1,
                        "files_sha256": {name: "x" for name in FOLD_FILES},
                    }
                    for i in range(1, 10)
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "cold.json"
    monkeypatch.setattr("scripts.benchmark_rolling_cold.sha256_file", lambda _: "test-source")
    monkeypatch.setattr("scripts.benchmark_rolling_cold.verify_fold_files", lambda *a: None)

    def read_parquet(path, **kwargs):
        name = str(path)
        if name.endswith("cold_targets.parquet"):
            return pd.DataFrame({"item_id": ["A"]})
        if name.endswith("items_train.parquet"):
            return pd.DataFrame({"item_id": ["A"]})
        return pd.DataFrame({"timestamp": [1], "item_id": ["A"]})

    monkeypatch.setattr("scripts.benchmark_rolling_cold.pd.read_parquet", read_parquet)
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_rolling_cold",
            "--input-path",
            str(tmp_path / "source.parquet"),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--max-fold",
            "1",
        ],
    )
    from scripts import benchmark_rolling_cold as cold_module

    original_metrics = cold_module._metrics
    calls = 0

    def fail_second(targets, ranking):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted")
        return original_metrics(targets, ranking)

    monkeypatch.setattr(cold_module, "_metrics", fail_second)
    with pytest.raises(RuntimeError, match="interrupted"):
        cold_main()
    assert len(json.loads(output.read_text(encoding="utf-8"))["results"]) == 1

    monkeypatch.setattr(cold_module, "_metrics", original_metrics)
    cold_main()
    assert len(json.loads(output.read_text(encoding="utf-8"))["results"]) == 2


def test_full_reference_run_requires_completed_sweeps(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol_version": "rolling-temporal",
                "source_sha256": "x",
                "n_windows": 10,
                "min_train_interactions": 1,
                "raw_property_sha256": {
                    "item_properties_part1.csv": "x",
                    "item_properties_part2.csv": "y",
                },
                "folds": [
                    {
                        "fold_index": index,
                        "warm_target_users": 10,
                        "files_sha256": {name: "x" for name in FOLD_FILES},
                    }
                    for index in range(1, 10)
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "benchmark_rolling",
            "--manifest",
            str(manifest),
            "--output",
            str(tmp_path / "results.json"),
        ],
    )

    with pytest.raises(ValueError, match="before viewing fold 5-9"):
        benchmark_main()


def test_completed_sweep_guard_rejects_mixed_final_configs(tmp_path):
    manifest = {
        "protocol_version": "rolling-temporal",
        "source_sha256": "same-source",
        "n_windows": 10,
        "min_train_interactions": 1,
        "raw_property_sha256": {
            "item_properties_part1.csv": "x",
            "item_properties_part2.csv": "y",
        },
        "folds": [
            {
                "fold_index": i,
                "warm_target_users": 10,
                "files_sha256": {name: "x" for name in FOLD_FILES},
            }
            for i in range(1, 10)
        ],
    }
    for model in ("item_knn", "als"):
        selected = {"parameter": 1}
        artifact = {
            "protocol_version": "rolling-temporal",
            "source_sha256": "same-source",
            "manifest_sha256": manifest_fingerprint(manifest),
            "model": model,
            "blind_holdout": False,
            "selected_config": selected,
            "results": [
                {
                    "phase": "final",
                    "fold_index": i,
                    "evaluation_users": 10,
                    "config": selected,
                }
                for i in range(5, 10)
            ],
            "final_summary": {"user_window_targets": 50},
        }
        (tmp_path / f"{model}_sweep.json").write_text(json.dumps(artifact), encoding="utf-8")

    require_completed_sweeps(tmp_path, manifest)
    changed_manifest = json.loads(json.dumps(manifest))
    changed_manifest["raw_property_sha256"]["item_properties_part1.csv"] = "changed"
    with pytest.raises(ValueError, match="Complete .*item_knn_sweep"):
        require_completed_sweeps(tmp_path, changed_manifest)
    path = tmp_path / "als_sweep.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["results"][-1]["config"] = {"parameter": 2}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="Complete .*als_sweep"):
        require_completed_sweeps(tmp_path, manifest)


def test_resume_rejects_final_rows_from_old_selection():
    artifact = {
        "results": [
            {
                "phase": "final",
                "fold_index": 5,
                "config": {"shrinkage_lambda": 10.0},
            }
        ]
    }
    with pytest.raises(ValueError, match="another selected configuration"):
        _validate_final_checkpoint(artifact, {"shrinkage_lambda": 100.0})


def test_reference_runner_rejects_invalid_max_fold(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"protocol_version": "rolling-temporal"}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["benchmark_rolling", "--manifest", str(manifest), "--max-fold", "0"],
    )
    with pytest.raises(ValueError, match="max-fold must be between 1 and 9"):
        benchmark_main()
