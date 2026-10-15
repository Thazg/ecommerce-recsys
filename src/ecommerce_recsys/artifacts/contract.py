"""Versioned snapshot identity, component inventory and safe local file loading."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import warnings
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from ecommerce_recsys.ranking.dataset import EVENT_TYPES, SOURCE_NAMES

FEATURE_NAMES = (
    "retrieval_rank",
    "rrf_score",
    "source_count",
    "user_event_count",
    "user_distinct_item_count",
    "user_days_since_last_event",
    "item_event_count",
    "item_distinct_user_count",
    "item_days_since_last_event",
    "category_known",
    "user_category_event_count",
    *(name for event in EVENT_TYPES for name in (f"user_{event}_count", f"item_{event}_count")),
    *(f"{source}_{suffix}" for source in SOURCE_NAMES for suffix in ("present", "rank", "score")),
)
POLICY = {
    "warm": "hybrid_learned",
    "cold": "recent_popularity",
    "candidate_budget": 1000,
    "output_limit": 20,
    "rrf_constant": 60,
    "recent_days": 30,
    "category_bonus": 0,
    "history": "full snapshot seen set; no post-cutoff updates",
    "tie_break": "descending score, ascending string item ID",
    "feature_transform": "reciprocal rank 60; log1p counts/ages; signed log1p source scores",
}
COMPONENTS = frozenset(
    {
        "users.parquet",
        "items.parquet",
        "affinities.parquet",
        "neighbors.parquet",
        "user_factors.npy",
        "item_factors.npy",
        "seen_indptr.npy",
        "seen_indices.npy",
        "weights.npy",
        "scales.npy",
        "references.json",
    }
)
RUNTIME_FILES = (
    "__init__.py",
    "artifacts/__init__.py",
    "artifacts/contract.py",
    "artifacts/runtime.py",
    "artifacts/adapters.py",
    "recommendation/__init__.py",
    "recommendation/matrix_factorization.py",
    "recommendation/item_knn.py",
    "recommendation/popularity.py",
    "recommendation/recent_popularity.py",
    "retrieval/base.py",
    "retrieval/__init__.py",
    "retrieval/mf_retriever.py",
    "retrieval/item_knn_retriever.py",
    "retrieval/popularity_retriever.py",
    "retrieval/category_retriever.py",
    "retrieval/hybrid_candidates.py",
    "ranking/dataset.py",
    "ranking/__init__.py",
)
# Reviewed schema-1 reader predecessor. Only loader IO/compatibility changed;
# its model inference AST, policy, features and dependencies must still match.
REVIEWED_READERS = {
    "f42f5c897858698eb9d6a0e8ed482e716dfb3d501f34c74e1c65ab79cc5c619c": "275e4d65ca7bc0414f8ae61900949b6ac29a144c5d28b3cafcda6db4737220ce",
}


class RuntimeCompatibilityWarning(UserWarning):
    """Host differs from the producer; numeric parity needs host validation."""


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def runtime_code() -> str:
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in RUNTIME_FILES
        }
    )


def inference_code() -> str:
    """Fingerprint prediction behavior separately from manifest/loader IO.

    This supports only explicitly reviewed reader predecessors; it does not
    accept arbitrary stale implementation hashes or model refactors.
    """
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "artifacts/runtime.py").read_text(encoding="utf-8"))
    tree.body = [
        node
        for node in tree.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        or node.name != "load_bundle"
    ]
    return digest(
        {
            "policy": POLICY,
            "features": list(FEATURE_NAMES),
            "runtime_ast": ast.dump(tree, include_attributes=False),
            "dependencies": {
                name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                for name in RUNTIME_FILES
                if name not in {"artifacts/contract.py", "artifacts/runtime.py"}
            },
        }
    )


def environment() -> dict:
    return {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        **{
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "pandas", "pyarrow", "implicit", "threadpoolctl")
        },
    }


def check_environment(recorded: dict) -> None:
    """Require Python major/minor and exact libraries; host identity is advisory."""
    current = environment()
    if (
        not isinstance(recorded, dict)
        or set(recorded) != set(current)
        or any(not isinstance(value, str) or not value for value in recorded.values())
    ):
        raise ValueError("Malformed recorded numerical environment.")

    def python_minor(value):
        match = re.fullmatch(r"(\d+)\.(\d+)\.\d+", value)
        return match.groups() if match else None

    if python_minor(recorded["python"]) is None or python_minor(recorded["python"]) != python_minor(
        current["python"]
    ):
        raise ValueError("Bundle requires the recorded Python major/minor version.")
    for name in set(current) - {"python", "system", "machine"}:
        if recorded[name] != current[name]:
            raise ValueError(f"Bundle requires {name}=={recorded[name]}; found {current[name]}.")
    if any(recorded[name] != current[name] for name in ("system", "machine")):
        warnings.warn(
            f"Bundle producer host {recorded['system']}/{recorded['machine']} differs from "
            f"{current['system']}/{current['machine']}. Versions are compatible; verify "
            "prediction parity and resource use on this host before deployment.",
            RuntimeCompatibilityWarning,
            stacklevel=2,
        )


def version_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("Bundle version must be a safe name of 1–80 characters.")
    if value.endswith(".") or value.upper().split(".")[0] in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("Bundle version is not a portable directory name.")
    return value


def write_json(path: Path, value: object) -> None:
    pending = path.with_suffix(path.suffix + ".tmp")
    payload = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    try:
        with pending.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        # A killed process cannot run finally; incomplete staging is retained.
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def component_record(path: Path, *, include_hash: bool = True) -> dict:
    """Describe a component; hash-free mode follows complete inventory verification."""
    record = {"bytes": path.stat().st_size}
    if include_hash:
        record["sha256"] = file_sha(path)
    if path.suffix == ".npy":
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        record.update(shape=list(array.shape), dtype=str(array.dtype))
    elif path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        record.update(rows=parquet.metadata.num_rows, schema=str(parquet.schema_arrow))
    return record


def verify_inventory(root: Path, expected_manifest_sha256: str | None = None) -> dict:
    """Check inventory and all byte hashes before deserializing model components."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Bundle must be an existing nonsymlink directory.")
    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("Bundle cannot contain symlinks or nested directories.")
    if {path.name for path in entries} != COMPONENTS | {"model_manifest.json"}:
        raise ValueError("Bundle inventory has missing or unexpected component files.")
    path = root / "model_manifest.json"
    if expected_manifest_sha256 is not None and file_sha(path) != expected_manifest_sha256:
        raise ValueError("Externally pinned manifest digest differs.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if (
        manifest.get("schema_version") != 1
        or type(manifest["schema_version"]) is not int
        or manifest.get("content_sha256") != digest(unsigned)
        or manifest.get("policy") != POLICY
        or manifest.get("feature_names") != list(FEATURE_NAMES)
        or set(manifest.get("components", {})) != COMPONENTS
    ):
        raise ValueError(
            "Unsupported or stale manifest identity, runtime, feature contract or policy."
        )
    recorded_code = manifest.get("runtime_code_sha256")
    if not isinstance(recorded_code, str) or (
        recorded_code != runtime_code()
        and (
            recorded_code not in REVIEWED_READERS
            or inference_code() != REVIEWED_READERS[recorded_code]
        )
    ):
        raise ValueError("Unsupported or stale runtime implementation; inference differs.")
    check_environment(manifest.get("runtime"))
    version_name(manifest["bundle_version"])
    snapshot = manifest["snapshot"]
    for key in ("fold_index", "cutoff", "ranker_label_cutoff", "users", "items", "events"):
        if type(snapshot.get(key)) is not int or snapshot[key] < 1:
            raise ValueError("Snapshot counts and timestamps must be positive plain integers.")
    if not 5 <= snapshot["fold_index"] <= 9 or snapshot["ranker_label_cutoff"] > snapshot["cutoff"]:
        raise ValueError("Ranker labels exceed the snapshot training cutoff.")
    configs = snapshot.get("configs", {})
    als, knn = configs.get("als", {}), configs.get("item_knn", {})
    if (
        set(configs) != {"als", "item_knn"}
        or set(als) != {"factors", "iterations", "regularization"}
        or set(knn) != {"shrinkage_lambda"}
        or any(type(als[key]) is not int or als[key] <= 0 for key in ("factors", "iterations"))
        or any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in (als.get("regularization"), knn.get("shrinkage_lambda"))
        )
        or snapshot.get("seeds") != {"als_fit": 42, "ranker_negative_sampling": 42}
    ):
        raise ValueError("Source model configuration or seed contract differs.")
    for name in sorted(COMPONENTS):
        entry = manifest["components"][name]
        if entry.get("bytes") != (root / name).stat().st_size or entry.get("sha256") != file_sha(
            root / name
        ):
            raise ValueError(f"Component checksum differs: {name}")
    return manifest
