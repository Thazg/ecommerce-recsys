"""Separate cross-platform audit policy; never changes model math or trace hashes."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np

from ecommerce_recsys.artifacts import load_bundle, runtime
from ecommerce_recsys.artifacts.contract import (
    digest,
    environment,
    file_sha,
    inference_code,
    runtime_code,
    write_json,
)

RTOL = ATOL = 1e-12
POLICY = {
    "verification": "isolated-linux-snapshot-v1",
    "rtol": RTOL,
    "atol": ATOL,
    "reference_side": "Windows producer-exact arrays",
    "equal_nan": False,
    "exact_fields": ["pool", "output", "evidence_sha256", "route"],
    "references": 101,
    "warm_references": 100,
    "cold_references": 1,
    "scope": "finite cross-platform qualification; original same-host bitwise policy unchanged",
}


def capture(bundle, user):
    """Observe the two original digest inputs, returning the original hashes unchanged."""
    arrays = []
    original = runtime.array_digest

    def observe(array):
        arrays.append(np.array(array, copy=True))
        return original(array)

    runtime.array_digest = observe
    try:
        trace = bundle.trace(user)
    finally:
        runtime.array_digest = original
    if len(arrays) != 2:
        raise ValueError("Original trace no longer exposes the two expected digest inputs.")
    return trace, arrays


def compare_arrays(actual, reference):
    if (
        actual.dtype != np.dtype("float64")
        or reference.dtype != actual.dtype
        or actual.shape != reference.shape
        or not np.isfinite(actual).all()
        or not np.isfinite(reference).all()
    ):
        raise ValueError("Array shape/dtype/finiteness differs; broadcasting is forbidden.")
    error = np.abs(actual - reference)
    return {
        "passed": bool(np.allclose(actual, reference, rtol=RTOL, atol=ATOL, equal_nan=False)),
        "max_abs_error": float(error.max(initial=0)),
        "max_error_over_allowed": float((error / (ATOL + RTOL * np.abs(reference))).max(initial=0)),
    }


def exact_differences(actual, reference):
    """Floating tolerances never apply to candidate/evidence/output identity."""
    return [key for key in POLICY["exact_fields"] if actual[key] != reference[key]]


def build_reference(bundle_path, pin, output):
    output = Path(output)
    if output.exists():
        raise ValueError("Preserve numerical references; choose a new directory.")
    bundle = load_bundle(Path(bundle_path), expected_manifest_sha256=pin)
    host = environment()
    if host != bundle.manifest["runtime"]:
        raise ValueError("Reference export requires the original producer numerical environment.")
    records = json.loads((Path(bundle_path) / "references.json").read_text())
    if (
        len(records) != 101
        or len({r["user_id"] for r in records}) != 101
        or sum(r["trace"]["route"] == "hybrid_learned" for r in records) != 100
        or sum(r["trace"]["route"] == "recent_popularity" for r in records) != 1
    ):
        raise ValueError("Incomplete producer reference sample.")
    arrays = {}
    for i, row in enumerate(records):
        trace, observed = capture(bundle, row["user_id"])
        if trace != row["trace"]:
            raise ValueError("Original producer-exact trace check failed before array export.")
        for name, array in zip(("features", "scores"), observed, strict=True):
            compare_arrays(array, array)
            arrays[f"{i:03}_{name}"] = array
    output.mkdir(parents=True)
    archive = output / "numerics.npz"
    np.savez_compressed(archive, **arrays)
    data = {
        "schema_version": 1,
        "manifest_sha256": pin,
        "references_sha256": file_sha(Path(bundle_path) / "references.json"),
        "reference_order_sha256": digest([r["user_id"] for r in records]),
        "references": 101,
        "exact_producer_parity": True,
        "runtime": host,
        "runtime_code_sha256": runtime_code(),
        "inference_code_sha256": inference_code(),
        "archive_sha256": file_sha(archive),
    }
    write_json(output / "metadata.json", {**data, "payload_sha256": digest(data)})
    return file_sha(output / "metadata.json")


def open_reference(path, pin, manifest_pin, references_pin):
    path = Path(path)
    metadata = path / "metadata.json"
    if metadata.is_symlink() or metadata.stat().st_size > 65536 or file_sha(metadata) != pin:
        raise ValueError("Numerical reference metadata pin/budget differs.")
    data = json.loads(metadata.read_text())
    if (
        data.get("schema_version") != 1
        or data.get("payload_sha256")
        != digest({k: v for k, v in data.items() if k != "payload_sha256"})
        or data.get("manifest_sha256") != manifest_pin
        or data.get("references_sha256") != references_pin
        or data.get("references") != 101
        or data.get("exact_producer_parity") is not True
        or data.get("runtime_code_sha256") != runtime_code()
        or data.get("inference_code_sha256") != inference_code()
    ):
        raise ValueError("Numerical references do not bind the original model/reader.")
    archive = path / "numerics.npz"
    if (
        archive.is_symlink()
        or archive.stat().st_size > 64 * 1024**2
        or file_sha(archive) != data["archive_sha256"]
    ):
        raise ValueError("Numerical reference archive pin/budget differs.")
    expected = {f"{i:03}_{name}.npy" for i in range(101) for name in ("features", "scores")}
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if (
            len(entries) != 202
            or {e.filename for e in entries} != expected
            or sum(e.file_size for e in entries) > 64 * 1024**2
        ):
            raise ValueError("Numerical reference inventory/budget differs.")
    return np.load(archive, allow_pickle=False), data
