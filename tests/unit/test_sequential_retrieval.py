"""Causal transition retrieval and M12 selection/checkpoint guards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import scripts.benchmark_sequential as benchmark
from ecommerce_recsys.retrieval.sequential import TransitionTable, histories_for_users
from scripts.benchmark_sequential import (
    CONFIGS,
    _validate_rows,
    read_artifact,
    require_lock,
    select_ordered,
    validate_completion,
    write_artifact,
)


def events(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["user_id", "item_id", "timestamp"])


def test_same_timestamp_items_have_no_invented_order_and_duplicates_collapse() -> None:
    train = events(
        [
            ("u", "A", 1),
            ("u", "C", 2),
            ("u", "B", 2),
            ("u", "B", 2),
            ("u", "D", 3),
        ]
    )
    table = TransitionTable.fit(train, ["A", "B", "C", "D"], 3)
    assert table.counts["A"] == {"B": 1, "C": 1}
    assert table.counts["B"] == {"D": 1}
    assert table.counts["C"] == {"D": 1}
    assert "C" not in table.counts["B"]
    assert table.observations == 4
    assert histories_for_users(train, ["u"], 3)["u"] == (("A",), ("B", "C"), ("D",))


def test_order_weight_changes_ranking_on_same_pool_and_empty_has_no_fallback() -> None:
    train = events([("x", "A", 1), ("x", "X", 2), ("y", "B", 1), ("y", "Y", 2)])
    table = TransitionTable.fit(train, ["A", "B", "X", "Y"], 2)
    history = (("A",), ("B",))
    ordered = table.generate(history, 10, lookback=5, decay=0.5)
    equal = table.generate(history, 10, lookback=5, decay=None)
    assert [row.item_id for row in ordered] == ["Y", "X"]
    assert [row.item_id for row in equal] == ["X", "Y"]
    assert [row.evidence[0].rank for row in ordered] == [1, 2]
    assert table.generate((("A", "B", "X", "Y"),), 10, lookback=5, decay=0.5) == []


def test_repeats_are_not_self_transitions_and_full_history_is_filtered() -> None:
    train = events([("u", "A", 1), ("u", "A", 2), ("u", "B", 3)])
    table = TransitionTable.fit(train, ["A", "B"], 3)
    assert table.counts["A"] == {"B": 1}
    assert table.generate((("A",),), 5, lookback=5, decay=None)[0].item_id == "B"
    assert table.generate((("A",), ("B",)), 5, lookback=1, decay=None) == []


@pytest.mark.parametrize(
    ("train", "catalog", "cutoff"),
    [
        (events([("u", "A", 2)]), ["A"], 1),
        (events([("u", None, 1)]), ["A"], 1),
        (events([("u", "A", 1)]), ["A", "A"], 1),
        (events([("u", "A", 1)]), ["B"], 1),
    ],
)
def test_fit_refuses_future_null_or_inconsistent_catalog(train, catalog, cutoff) -> None:
    with pytest.raises(ValueError):
        TransitionTable.fit(train, catalog, cutoff)


def test_generate_rejects_invalid_policy_or_history() -> None:
    table = TransitionTable.fit(events([("u", "A", 1), ("u", "B", 2)]), ["A", "B"], 2)
    for kwargs in (
        {"lookback": True, "decay": 0.5},
        {"lookback": 5, "decay": 1.0},
        {"lookback": 5, "decay": float("nan")},
        {"lookback": 5, "decay": np.float32(np.nan)},
    ):
        with pytest.raises(ValueError):
            table.generate((("A",),), 10, **kwargs)
    for invalid_limit in (True, np.int64(10), 0):
        with pytest.raises(ValueError, match="limit"):
            table.generate((("A",),), invalid_limit, lookback=5, decay=None)
    with pytest.raises(ValueError):
        table.generate((("A", "A"),), 10, lookback=5, decay=None)
    with pytest.raises(ValueError, match="nonempty timestamp buckets"):
        table.generate((), 10, lookback=5, decay=None)


def test_lookback_excludes_older_buckets_and_equal_scores_use_item_id_ties() -> None:
    train = events([("x", "A", 1), ("x", "X", 2), ("y", "B", 1), ("y", "Y", 2)])
    table = TransitionTable.fit(train, ["A", "B", "X", "Y"], 2)
    history = (("A",), ("B",))
    assert [row.item_id for row in table.generate(history, 10, lookback=1, decay=None)] == ["Y"]
    assert [row.item_id for row in table.generate(history, 10, lookback=2, decay=None)] == [
        "X",
        "Y",
    ]


def test_observed_bucket_transitions_do_not_impose_a_session_gap() -> None:
    train = events([("u", "A", 1), ("u", "B", 1_000_000)])
    table = TransitionTable.fit(train, ["A", "B"], 1_000_000)
    assert table.counts["A"] == {"B": 1}
    assert table.observations == 1


def test_large_timestamp_baskets_count_each_cross_bucket_pair_once() -> None:
    prior = [("u", f"A{index}", 1) for index in range(20)]
    current = [("u", f"B{index}", 2) for index in range(20)]
    train = events([*prior, *current])
    table = TransitionTable.fit(train, [row[1] for row in [*prior, *current]], 2)
    assert table.observations == 400
    assert table.distinct_pairs == 400
    assert table.outgoing["A0"] == 20


@pytest.mark.parametrize("invalid", [True, 2.9, float("nan"), np.int64(2)])
def test_fold_cutoff_is_not_truncated_before_validation(invalid) -> None:
    with pytest.raises(ValueError, match="plain integers"):
        benchmark.evaluate_fold(
            fold={"fold_index": 1, "train_cutoff": invalid, "evaluation_cutoff": 3},
            interactions=events([("u", "A", 1)]),
            fold_dir=Path("."),
            names=("equal_h5",),
        )


def test_small_fold_runs_real_transition_source_without_mocked_retrieval(
    tmp_path: Path,
) -> None:
    train = events(
        [
            ("x", "A", 1),
            ("x", "X", 2),
            ("y", "B", 1),
            ("y", "Y", 2),
            ("u", "A", 1),
            ("u", "B", 2),
            *((f"z{index}", "A", 1) for index in range(14)),
        ]
    )
    targets = events([("u", "Y", 3)])
    catalog = pd.DataFrame({"item_id": ["A", "B", "X", "Y"]})
    fold_dir = tmp_path / "fold_01"
    fold_dir.mkdir()
    targets.to_parquet(fold_dir / "warm_targets.parquet", index=False)
    catalog.to_parquet(fold_dir / "items_train.parquet", index=False)
    fold = {
        "fold_index": 1,
        "train_cutoff": 2,
        "evaluation_cutoff": 3,
        "training_interactions": 20,
        "warm_target_users": 1,
        "train_catalog_items": 4,
    }
    row = benchmark.evaluate_fold(
        fold=fold,
        interactions=train,
        fold_dir=fold_dir,
        names=("ordered_h5_d05", "equal_h5"),
    )
    assert row["transition_observations"] == 3
    assert row["configs"]["ordered_h5_d05"]["totals"]["100"]["hits"] == 1
    assert row["configs"]["equal_h5"]["totals"]["100"]["hits"] == 1
    targets.astype({"timestamp": float}).to_parquet(fold_dir / "warm_targets.parquet", index=False)
    with pytest.raises(ValueError, match="evaluation window"):
        benchmark.evaluate_fold(
            fold=fold,
            interactions=train,
            fold_dir=fold_dir,
            names=("equal_h5",),
        )


def _selection_rows() -> list[dict]:
    rows = []
    for index in range(1, 5):
        configs = {
            name: {
                "totals": {
                    "100": {"hits": 1},
                    "1000": {"hits": 3},
                }
            }
            for name in CONFIGS
        }
        configs["ordered_h5_d08"]["totals"]["100"]["hits"] = 2
        rows.append({"fold_index": index, "configs": configs})
    return rows


def _checkpoint_rows() -> list[dict]:
    rows = _selection_rows()
    for index, row in enumerate(rows, start=1):
        row.update({"requests": 4, "cutoff": index, "catalog_items": 4, "fit_seconds": 0.1})
        for name, result in row["configs"].items():
            totals = {
                str(n): {
                    "hits": 2 if name == "ordered_h5_d08" and n == 100 else 1,
                    "candidate_count": 4,
                    "empty_requests": 0,
                    "full_requests": 0,
                    "unique_items": 1,
                }
                for n in (100, 500, 1000)
            }
            result.update(
                {
                    "evaluation_users": 4,
                    "reachable_targets": 4,
                    "retrieval_seconds": 0.1,
                    "totals": totals,
                    "metrics": {
                        f"Recall@{n}": totals[str(n)]["hits"] / 4 for n in (100, 500, 1000)
                    },
                }
            )
    return rows


def test_selection_requires_full_grid_and_binds_same_h_control() -> None:
    rows = _selection_rows()
    assert select_ordered(rows) == ("ordered_h5_d08", "equal_h5")
    del rows[0]["configs"]["equal_h20"]
    with pytest.raises(ValueError, match="full development grid"):
        select_ordered(rows)


def test_artifact_payload_tamper_and_missing_lock_are_rejected(tmp_path: Path) -> None:
    artifact_path = tmp_path / "development.json"
    identity = {"code_sha256": "source-a"}
    rows = _checkpoint_rows()
    write_artifact(
        artifact_path,
        {
            "benchmark": "sequential-development-v1",
            **identity,
            "folds": rows,
            "complete": True,
            "selected_ordered": "ordered_h5_d08",
            "selected_control": "equal_h5",
        },
    )
    expected = {"benchmark": "sequential-development-v1", **identity}
    assert read_artifact(artifact_path, expected)["complete"]
    manifest = {
        "folds": [
            {"warm_target_users": 4, "train_cutoff": index, "train_catalog_items": 4}
            for index in range(1, 5)
        ]
    }
    args = SimpleNamespace(
        development_artifact=artifact_path, selection_lock=tmp_path / "lock.json"
    )
    with pytest.raises(FileNotFoundError):
        require_lock(args, manifest, identity)
    artifact_path.write_text(
        artifact_path.read_text().replace('"complete": true', '"complete": false')
    )
    with pytest.raises(ValueError, match="payload"):
        read_artifact(artifact_path, expected)


def test_checkpoint_rejects_bad_fold_order_and_denominator() -> None:
    rows = _checkpoint_rows()
    manifest = {
        "folds": [
            {"warm_target_users": 4, "train_cutoff": index, "train_catalog_items": 4}
            for index in range(1, 5)
        ]
    }
    _validate_rows(rows, manifest, phase="development")
    rows[0]["configs"]["ordered_h5_d05"]["evaluation_users"] = 3
    with pytest.raises(ValueError, match="denominator"):
        _validate_rows(rows, manifest, phase="development")
    rows[0]["configs"]["ordered_h5_d05"]["evaluation_users"] = 4
    rows[0]["configs"]["ordered_h5_d05"]["metrics"]["Recall@100"] = 0.9
    with pytest.raises(ValueError, match="integer numerator"):
        _validate_rows(rows, manifest, phase="development")
    rows[0]["configs"]["ordered_h5_d05"]["metrics"]["Recall@100"] = 0.25
    rows[0]["fold_index"] = 2
    with pytest.raises(ValueError, match="fold order"):
        _validate_rows(rows, manifest, phase="development")


def test_completion_flag_cannot_call_partial_artifact_complete() -> None:
    with pytest.raises(ValueError, match="completion flag"):
        validate_completion({"folds": [1], "complete": True}, phase="diagnostic")
    validate_completion({"folds": [1], "complete": False}, phase="diagnostic")
    validate_completion({"folds": [1, 2, 3, 4, 5], "complete": True}, phase="diagnostic")


def test_partial_diagnostic_checkpoint_resumes_without_duplicate_fold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "folds": [
            {
                "fold_index": index,
                "warm_target_users": 4,
                "train_cutoff": index,
                "train_catalog_items": 4,
            }
            for index in range(1, 10)
        ]
    }
    args = SimpleNamespace(
        max_fold=5,
        diagnostic_artifact=tmp_path / "diagnostic.json",
        selection_lock=tmp_path / "lock.json",
        input_path=tmp_path / "data.parquet",
        fold_dir=tmp_path,
    )
    row = _checkpoint_rows()[0]
    row["fold_index"] = 5
    row["cutoff"] = 5
    row["configs"] = {name: row["configs"][name] for name in ("ordered_h5_d08", "equal_h5")}
    calls: list[int] = []

    def evaluate(**kwargs) -> dict:
        calls.append(kwargs["fold"]["fold_index"])
        return row

    monkeypatch.setattr(benchmark, "inputs", lambda *a, **k: (manifest, {"code_sha256": "a"}))
    monkeypatch.setattr(benchmark, "require_lock", lambda *a, **k: ("ordered_h5_d08", "equal_h5"))
    monkeypatch.setattr(benchmark, "sha256_file", lambda *a, **k: "lock-sha")
    monkeypatch.setattr(benchmark.pd, "read_parquet", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(benchmark, "evaluate_fold", evaluate)
    benchmark._diagnostic(args)
    first = args.diagnostic_artifact.read_bytes()
    assert not read_artifact(
        args.diagnostic_artifact,
        {"benchmark": "sequential-diagnostic-v1", "code_sha256": "a"},
    )["complete"]
    benchmark._diagnostic(args)
    assert args.diagnostic_artifact.read_bytes() == first
    assert calls == [5]
