"""Content fingerprints for rolling data and benchmark checkpoints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROPERTY_FILES = ("item_properties_part1.csv", "item_properties_part2.csv")
FOLD_FILES = ("warm_targets.parquet", "cold_targets.parquet", "items_train.parquet")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def property_hashes(raw_dir: Path) -> dict[str, str]:
    return {name: sha256_file(raw_dir / name) for name in PROPERTY_FILES}


def fold_hashes(fold_dir: Path) -> dict[str, str]:
    return {name: sha256_file(fold_dir / name) for name in FOLD_FILES}


def manifest_fingerprint(manifest: dict) -> str:
    """Bind artifacts to the complete source, metadata, cutoffs, and fold files."""
    if (
        set(manifest.get("raw_property_sha256", {})) != set(PROPERTY_FILES)
        or manifest.get("n_windows") != 10
        or manifest.get("min_train_interactions") != 1
        or [fold.get("fold_index") for fold in manifest.get("folds", [])] != list(range(1, 10))
    ):
        raise ValueError("Rolling manifest is incomplete or lacks raw-property provenance.")
    if any(set(fold.get("files_sha256", {})) != set(FOLD_FILES) for fold in manifest["folds"]):
        raise ValueError("Rolling manifest lacks fold-file fingerprints.")
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_fold_files(manifest: dict, fold_root: Path, max_fold: int = 9) -> None:
    """Reject changed or missing fold Parquet files, including cached-result runs."""
    for fold in manifest["folds"][:max_fold]:
        index = fold["fold_index"]
        path = fold_root / f"fold_{index:02d}"
        if fold_hashes(path) != fold.get("files_sha256"):
            raise ValueError(f"Fold {index} files do not match the rolling manifest.")
