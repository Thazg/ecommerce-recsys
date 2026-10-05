"""Validate completed rolling sweeps before exposing later-fold diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from ecommerce_recsys.data.rolling_provenance import manifest_fingerprint


def require_completed_sweeps(directory: Path, manifest: dict) -> None:
    """Reject missing, partial, or mixed-configuration final checkpoints."""
    if [fold["fold_index"] for fold in manifest["folds"]] != list(range(1, 10)):
        raise ValueError("Expected nine ordered rolling folds.")
    expected_folds = {
        fold["fold_index"]: fold["warm_target_users"] for fold in manifest["folds"][4:]
    }
    fingerprint = manifest_fingerprint(manifest)
    for model_name in ("item_knn", "als"):
        path = directory / f"{model_name}_sweep.json"
        if not path.exists():
            raise ValueError(f"Complete {path} before viewing fold 5-9 metrics.")
        sweep = json.loads(path.read_text(encoding="utf-8"))
        final = [row for row in sweep.get("results", []) if row.get("phase") == "final"]
        selected = sweep.get("selected_config")
        valid = (
            sweep.get("protocol_version") == manifest["protocol_version"]
            and sweep.get("source_sha256") == manifest["source_sha256"]
            and sweep.get("manifest_sha256") == fingerprint
            and sweep.get("model") == model_name
            and sweep.get("blind_holdout") is False
            and isinstance(selected, dict)
            and len(final) == len(expected_folds)
            and {row.get("fold_index") for row in final} == set(expected_folds)
            and all(
                row.get("config") == selected
                and row.get("evaluation_users") == expected_folds[row["fold_index"]]
                for row in final
            )
            and sweep.get("final_summary", {}).get("user_window_targets")
            == sum(expected_folds.values())
        )
        if not valid:
            raise ValueError(f"Complete {path} before viewing fold 5-9 metrics.")
