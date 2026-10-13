"""Behavior and artifact guards for fixed-pool category re-ranking."""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.ranking.diversity import category_novelty_order
from scripts import benchmark_diversity as diversity_runner
from scripts.benchmark_diversity import (
    BONUSES,
    ReRankingTotals,
    _validate_completion,
    category_map,
    check_base_parity,
    diagnostic_keys,
    read_artifact,
    run_diagnostic,
    select_bonus,
    write_artifact,
)


def test_zero_bonus_matches_learned_order_and_prefixes() -> None:
    ids = ["c", "a", "b", "d"]
    scores = np.array([3.0, 3.0, 2.0, 1.0])
    categories = ["x", "x", "y", None]
    assert category_novelty_order(ids, scores, categories, bonus=0, limit=4) == (1, 0, 2, 3)
    assert (
        category_novelty_order(ids, scores, categories, bonus=0.2, limit=2)
        == category_novelty_order(ids, scores, categories, bonus=0.2, limit=4)[:2]
    )


def test_known_novelty_and_unknown_categories() -> None:
    ids = ["a", "b", "c", "d"]
    scores = [4.0, 3.0, 2.0, 1.0]
    categories = ["x", "x", "y", None]
    assert category_novelty_order(ids, scores, categories, bonus=0.5, limit=2) == (0, 2)
    assert category_novelty_order(ids, scores, [None] * 4, bonus=1, limit=4) == (0, 1, 2, 3)
    assert category_novelty_order([], [], [], bonus=0) == ()


def test_positive_bonus_tie_preserves_learned_order() -> None:
    ids = ["a", "b", "c"]
    assert category_novelty_order(ids, [3.0, 2.0, 1.0], ["x", "x", "y"], bonus=0.5, limit=3) == (
        0,
        1,
        2,
    )


def test_single_category_and_score_magnitude_contract() -> None:
    ids = ["a", "b", "c", "d"]
    categories = ["x", "x", "y", "z"]
    steep = category_novelty_order(ids, [100.0, 99.0, 0.0, -1.0], categories, bonus=0.5, limit=4)
    flat = category_novelty_order(ids, [100.0, 51.0, 50.0, -1.0], categories, bonus=0.5, limit=4)
    assert steep == flat
    assert steep != (0, 1, 2, 3)
    assert category_novelty_order(ids, [4.0, 3.0, 2.0, 1.0], ["x"] * 4, bonus=1.0, limit=4) == (
        0,
        1,
        2,
        3,
    )


def test_bonus_reach_depends_on_shortlist_length_and_excludes_rank_101() -> None:
    short = category_novelty_order(
        [str(i) for i in range(5)],
        [5.0, 4.0, 3.0, 2.0, 1.0],
        ["x", "x", "x", "x", "y"],
        bonus=0.1,
        limit=2,
    )
    long = category_novelty_order(
        [str(i) for i in range(100)],
        list(reversed(range(100))),
        ["y" if i == 5 else "x" for i in range(100)],
        bonus=0.1,
        limit=2,
    )
    assert short == (0, 1)
    assert long == (0, 5)

    beyond = category_novelty_order(
        [str(i) for i in range(101)],
        list(reversed(range(101))),
        ["y" if i == 100 else "x" for i in range(101)],
        bonus=1.0,
        limit=20,
    )
    assert beyond == tuple(range(20))


@pytest.mark.parametrize(
    "ids,scores,categories,bonus",
    [
        (["a", "a"], [1, 2], ["x", "y"], 0),
        (["a"], [float("nan")], ["x"], 0),
        (["a"], [np.float32(float("inf"))], ["x"], 0),
        (["a"], [1], [""], 0),
        (["a"], [1], ["x"], True),
        (["a"], [1], ["x"], -0.1),
        (["a"], [1], ["x"], float("nan")),
    ],
)
def test_invalid_rerank_inputs(ids, scores, categories, bonus) -> None:
    with pytest.raises(ValueError):
        category_novelty_order(ids, scores, categories, bonus=bonus)


def test_invalid_output_limit() -> None:
    with pytest.raises(ValueError, match="limits"):
        category_novelty_order(["a"], [1.0], ["x"], bonus=0.0, limit=0)


def test_train_catalog_category_scope() -> None:
    catalog = pd.DataFrame({"item_id": ["a", "b"], "category_id": ["x", None]})
    assert category_map(catalog, expected_items=2) == {"a": "x", "b": None}
    with pytest.raises(ValueError, match="duplicate"):
        category_map(pd.concat([catalog, catalog.iloc[[0]]]), expected_items=3)


def test_totals_preserve_zero_positive_denominator() -> None:
    total = ReRankingTotals(catalog_size=4)
    total.add(
        item_ids=["a", "b"],
        categories=["x", "x"],
        target_item="z",
        target_in_pool=False,
        order=(0, 1),
    )
    total.add(
        item_ids=["a", "c"],
        categories=["x", None],
        target_item="c",
        target_in_pool=True,
        order=(0, 1),
    )
    result = total.output()
    assert result["requests"] == 2
    assert result["hits"]["20"] == 1
    assert result["HR@20"] == 0.5
    assert result["MRR@20"] == 0.25
    assert result["NDCG@20"] == (1 / np.log2(3)) / 2
    assert result["known_category_item_slots@20"] == 3 / 40
    assert result["distinct_known_category_slots@20"] == 2 / 40
    assert result["item_coverage@20"] == 3 / 4


def _selection_rows(bonus_hits: int = 100) -> list[dict]:
    rows = []
    for fold in (2, 3, 4):
        configs = {}
        for bonus in BONUSES:
            configs[str(bonus)] = {
                "distinct_known_category_slots": 100 if bonus == 0 else 110,
                "known_category_item_slots": 200,
                "hits": {"20": 100 if bonus == 0 else bonus_hits},
                "discounted_sum": {"20": 80.0},
            }
        rows.append({"fold_index": fold, "requests": 1000, "configs": configs})
    return rows


def test_selection_uses_development_only_and_gates_relevance() -> None:
    assert select_bonus(_selection_rows()) == 0.05
    assert select_bonus(_selection_rows(bonus_hits=90)) == 0.0
    with pytest.raises(ValueError, match="complete"):
        select_bonus(_selection_rows()[:2])


def test_selection_gates_ndcg_and_known_category_slots() -> None:
    ndcg_loss = _selection_rows()
    for row in ndcg_loss:
        for bonus in BONUSES[1:]:
            row["configs"][str(bonus)]["discounted_sum"]["20"] = 78.0
    assert select_bonus(ndcg_loss) == 0.0

    metadata_loss = _selection_rows()
    for row in metadata_loss:
        for bonus in BONUSES[1:]:
            row["configs"][str(bonus)]["known_category_item_slots"] = 0
    assert select_bonus(metadata_loss) == 0.0


def test_selection_pools_folds_and_breaks_ties_by_distinct_categories() -> None:
    rows = _selection_rows()
    rows[0]["configs"]["0.05"]["hits"]["20"] = 98
    rows[1]["configs"]["0.05"]["hits"]["20"] = 102
    assert select_bonus(rows) == 0.05

    for row in rows:
        row["configs"]["0.1"]["distinct_known_category_slots"] = 111
        row["configs"]["0.1"]["hits"]["20"] = 99
    assert select_bonus(rows) == 0.1


def test_incomplete_checkpoint_and_invalid_diagnostic_boundary() -> None:
    with pytest.raises(ValueError, match="completion"):
        _validate_completion({"folds": [{}], "complete": True}, phase="diagnostic")
    with pytest.raises(ValueError, match="max fold"):
        run_diagnostic(argparse.Namespace(max_fold=4))


def test_diagnostic_control_runs_first_with_stable_keys() -> None:
    assert diagnostic_keys(0.1) == ("0.0", "0.1")
    assert diagnostic_keys(0.0) == ("0.0",)


def test_fingerprint_uses_published_upstream_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        diversity_runner, "historical_upstream_fingerprints", lambda: ("m10", "m11")
    )
    original = diversity_runner.code_fingerprint()
    monkeypatch.setattr(diversity_runner.ranker, "code_fingerprint", lambda: "future-src-drift")
    assert diversity_runner.code_fingerprint() == original
    monkeypatch.setattr(
        diversity_runner, "historical_upstream_fingerprints", lambda: ("m10", "changed-m11")
    )
    assert diversity_runner.code_fingerprint() != original


def test_parity_rejects_changed_order() -> None:
    result = {
        "requests": 2,
        "target_in_pool": 1,
        "candidate_count": 3,
        "hits": {str(k): 1 for k in (5, 10, 20)},
        **{f"{metric}@{k}": 0.5 for metric in ("HR", "MRR", "NDCG") for k in (5, 10, 20)},
    }
    upstream = {
        "requests": 2,
        "target_in_pool": 1,
        "candidates": 3,
        "learned": {"hits": result["hits"].copy(), **{k: v for k, v in result.items() if "@" in k}},
    }
    check_base_parity(result, upstream)
    result["hits"]["20"] = 0
    with pytest.raises(ValueError, match="order"):
        check_base_parity(result, upstream)


def test_artifact_rejects_tamper_and_identity_change(tmp_path) -> None:
    path = tmp_path / "development.json"
    write_artifact(path, {"benchmark": "development", "policy": {"bonus": 0.1}})
    read_artifact(path, {"benchmark": "development", "policy": {"bonus": 0.1}})
    with pytest.raises(ValueError, match="provenance"):
        read_artifact(path, {"benchmark": "development", "policy": {"bonus": 0.2}})
    data = json.loads(path.read_text(encoding="utf-8"))
    data["policy"]["bonus"] = 0.3
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="payload"):
        read_artifact(path, {"benchmark": "development"})
