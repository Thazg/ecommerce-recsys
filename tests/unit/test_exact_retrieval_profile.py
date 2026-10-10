"""Exact retrieval cost sampling and checkpoint integrity."""

import copy

import pandas as pd
import pytest

from scripts.profile_exact_retrieval import (
    POLICY,
    _results_sha256,
    _sample_indices,
    _validate_checkpoint,
)


def test_profile_sample_is_stratified_deterministic_and_unique() -> None:
    targets = pd.DataFrame({"user_id": [str(i) for i in range(16)]})
    histories = {str(i): tuple(str(x) for x in range(i + 1)) for i in range(16)}
    first = _sample_indices(targets, histories, seed=42, size=8)
    second = _sample_indices(targets, histories, seed=42, size=8)
    assert first.tolist() == second.tolist()
    assert len(set(first)) == 8
    assert [sum(start <= index < start + 4 for index in first) for start in range(0, 16, 4)] == [
        2
    ] * 4


def test_profile_checkpoint_rejects_changed_decision_or_fold_gap() -> None:
    identity = {"policy": POLICY, "runner_sha256": "code"}
    rows = [{"fold_index": fold, "latency": {"latency_p95_ms": 8.0}} for fold in POLICY["folds"]]
    valid = {
        **identity,
        "results": rows,
        "results_sha256": _results_sha256(rows),
        "completed_folds": POLICY["folds"],
        "complete": True,
        "decision": "no-go: exact retrieval below cost trigger",
    }
    _validate_checkpoint(valid, identity)
    changed = copy.deepcopy(valid)
    changed["decision"] = "proceed to ANN compatibility pilot"
    with pytest.raises(ValueError, match="decision"):
        _validate_checkpoint(changed, identity)
    changed = copy.deepcopy(valid)
    changed["results"] = [rows[1]]
    changed["results_sha256"] = _results_sha256(changed["results"])
    changed["completed_folds"] = [2]
    changed["complete"] = False
    changed["decision"] = "pending"
    with pytest.raises(ValueError, match="fold"):
        _validate_checkpoint(changed, identity)
