"""Write fitted source state without pickle; seal and publish immutable versions."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ecommerce_recsys.artifacts.adapters import capture_tables, validate_state
from ecommerce_recsys.artifacts.contract import (
    COMPONENTS,
    FEATURE_NAMES,
    POLICY,
    component_record,
    digest,
    environment,
    runtime_code,
    verify_inventory,
    version_name,
    write_json,
)


def export_bundle(
    parent: Path,
    version: str,
    *,
    sources,
    features,
    weights,
    scales,
    snapshot: dict,
    provenance: dict,
    references: list[dict],
) -> Path:
    """Stage once and atomically publish; never overwrite an existing bundle.

    An interrupted unsealed staging directory is retained for inspection. It is
    not silently merged with a new fit; a new version/path is required.
    """
    version_name(version)
    parent.mkdir(parents=True, exist_ok=True)
    destination, staging = parent / version, parent / f".{version}.building"
    if destination.exists() or staging.exists():
        raise FileExistsError(
            "Bundle version or staging path exists; verify/resume it or choose a new version."
        )
    staging.mkdir()
    by_name = {source.name: source for source in sources}
    als = by_name["als"].model
    tables = capture_tables(by_name, features, als)
    arrays = {
        "user_factors": als._model.user_factors,
        "item_factors": als._model.item_factors,
        "seen_indptr": als._user_item_matrix.indptr,
        "seen_indices": als._user_item_matrix.indices,
        "weights": np.asarray(weights, dtype=np.float64),
        "scales": np.asarray(scales, dtype=np.float64),
    }
    validate_state(tables, arrays, snapshot)
    for name, frame in tables.items():
        frame.to_parquet(staging / f"{name}.parquet", index=False)
    for name, array in arrays.items():
        np.save(staging / f"{name}.npy", array, allow_pickle=False)
    write_json(staging / "references.json", references)
    manifest = {
        "schema_version": 1,
        "bundle_version": version,
        "snapshot": snapshot,
        "provenance": provenance,
        "policy": POLICY,
        "feature_names": list(FEATURE_NAMES),
        "runtime": environment(),
        "runtime_code_sha256": runtime_code(),
        "components": {name: component_record(staging / name) for name in sorted(COMPONENTS)},
    }
    manifest["content_sha256"] = digest(manifest)
    write_json(staging / "model_manifest.json", manifest)
    verify_inventory(staging)
    staging.rename(destination)
    return destination


def recover_sealed_bundle(parent: Path, version: str, expected_provenance: dict) -> Path | None:
    """Resume only a fully sealed matching fit; never refit over partial state."""
    version_name(version)
    destination, staging = parent / version, parent / f".{version}.building"
    if destination.exists() and staging.exists():
        raise ValueError(
            "Both published and staging versions exist; resolve the collision explicitly."
        )
    existing = destination if destination.exists() else staging
    if not existing.exists():
        return None
    manifest = verify_inventory(existing)
    if manifest["bundle_version"] != version or manifest["provenance"] != expected_provenance:
        raise ValueError("Existing bundle provenance differs; use a distinct version.")
    if existing == staging:
        staging.rename(destination)
    return destination
