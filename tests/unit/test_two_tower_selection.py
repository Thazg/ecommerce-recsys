import json
from pathlib import Path

import pytest

from scripts.benchmark_two_tower import (
    ALS_CONFIGS,
    M7_REFERENCE_ALS_CONFIG,
    POLICY,
    TWO_TOWER_CONFIGS,
    _canonical_sha256,
    _diagnostic_configs,
    _results_sha256,
    _runner_sha256,
    _save,
    _validate_checkpoint,
)
from scripts.lock_two_tower_configs import _select


def test_two_tower_selection_requires_full_development_grid_and_uses_pooled_integer_hits(tmp_path):
    rows = []
    for config_index, config in enumerate(TWO_TOWER_CONFIGS):
        for fold in range(1, 5):
            rows.append(
                {
                    "config": config,
                    "fold_index": fold,
                    "phase": "development",
                    "evaluation_users": 100,
                    "totals": {
                        "100": {"hits": 10 + config_index},
                        "1000": {"hits": 30 + config_index},
                    },
                    "model_cost": {"parameter_bytes": 1000 + config_index},
                }
            )
    artifact = {
        "model": "two_tower",
        "phase": "development",
        "blind_holdout": False,
        "configurations": list(TWO_TOWER_CONFIGS),
        "policy": POLICY,
        "policy_sha256": _canonical_sha256(POLICY),
        "runner_sha256": _runner_sha256(Path(__file__).resolve().parents[2]),
        "runtime": {"python": "3.13.15", "torch": "2.14.1+cpu"},
        "manifest_sha256": "b" * 64,
        "input_sha256": "a" * 64,
        "expected_folds": [1, 2, 3, 4],
        "completed_folds": [1, 2, 3, 4],
        "complete": True,
        "results": rows,
    }
    artifact["results_sha256"] = _results_sha256(artifact)
    path = tmp_path / "development.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    selected = _select(path, "two_tower", TWO_TOWER_CONFIGS)
    assert selected["selected_config"] == TWO_TOWER_CONFIGS[-1]
    assert selected["development_user_windows"] == 400
    assert selected["development_hits_at_1000"] == (30 + 3) * 4

    artifact["results"].pop()
    artifact["completed_folds"] = [1, 2, 3]
    artifact["complete"] = False
    artifact["results_sha256"] = _results_sha256(artifact)
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="complete"):
        _select(path, "two_tower", TWO_TOWER_CONFIGS)


def test_two_tower_selection_rejects_policy_or_runner_drift(tmp_path):
    artifact = {
        "model": "two_tower",
        "phase": "development",
        "blind_holdout": False,
        "configurations": list(TWO_TOWER_CONFIGS),
        "policy": {**POLICY, "epochs": 10},
        "policy_sha256": _canonical_sha256({**POLICY, "epochs": 10}),
        "runner_sha256": _runner_sha256(Path(__file__).resolve().parents[2]),
        "runtime": {"python": "3.13.15", "torch": "2.14.1+cpu"},
        "manifest_sha256": "b" * 64,
        "input_sha256": "a" * 64,
        "expected_folds": [1, 2, 3, 4],
        "completed_folds": [1, 2, 3, 4],
        "complete": True,
        "results": [
            {
                "config": cfg,
                "fold_index": fold,
                "phase": "development",
                "evaluation_users": 1,
                "totals": {"100": {"hits": 0}, "1000": {"hits": 0}},
                "model_cost": {"parameter_bytes": 1},
            }
            for cfg in TWO_TOWER_CONFIGS
            for fold in range(1, 5)
        ],
    }
    artifact["results_sha256"] = _results_sha256(artifact)
    path = tmp_path / "development.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="recognized Two-Tower policy"):
        _select(path, "two_tower", TWO_TOWER_CONFIGS)

    artifact["policy"] = POLICY
    artifact["policy_sha256"] = _canonical_sha256(POLICY)
    artifact["runner_sha256"] = "0" * 64
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="runner differs"):
        _select(path, "two_tower", TWO_TOWER_CONFIGS)


def test_two_tower_checkpoint_is_atomic_and_detects_row_changes(tmp_path):
    config = TWO_TOWER_CONFIGS[0]
    reversed_config = dict(reversed(list(config.items())))
    identity = {
        "model": "two_tower",
        "phase": "development",
        "configurations": [config],
        "expected_folds": [1, 2, 3, 4],
    }
    artifact = {
        **identity,
        "results": [
            {"config": reversed_config, "fold_index": 1, "phase": "development", "metrics": {}}
        ],
        "completed_folds": [1],
        "complete": False,
    }
    path = tmp_path / "checkpoint.json"
    _save(path, artifact)
    _validate_checkpoint(artifact, identity)
    assert not path.with_suffix(".json.tmp").exists()
    artifact["results"][0]["metrics"]["Recall@1000"] = 0.5
    with pytest.raises(ValueError, match="fingerprint"):
        _validate_checkpoint(artifact, identity)


def test_partial_diagnostic_checkpoint_is_explicitly_incomplete(tmp_path):
    config = TWO_TOWER_CONFIGS[0]
    identity = {
        "model": "two_tower",
        "phase": "diagnostic",
        "configurations": [config],
        "expected_folds": [5, 6, 7, 8, 9],
    }
    artifact = {
        **identity,
        "results": [{"config": config, "fold_index": 5, "phase": "diagnostic"}],
        "completed_folds": [5],
        "complete": False,
    }
    _save(tmp_path / "partial.json", artifact)
    _validate_checkpoint(artifact, identity)
    assert artifact["complete"] is False


def test_als_diagnostic_deduplicates_m7_reference_when_it_is_selected():
    assert M7_REFERENCE_ALS_CONFIG in ALS_CONFIGS
    assert _diagnostic_configs("als", M7_REFERENCE_ALS_CONFIG) == (M7_REFERENCE_ALS_CONFIG,)


def test_als_diagnostic_keeps_locked_and_m7_reference_configs_when_distinct():
    locked = next(config for config in ALS_CONFIGS if config != M7_REFERENCE_ALS_CONFIG)
    assert _diagnostic_configs("als", locked) == (locked, M7_REFERENCE_ALS_CONFIG)
