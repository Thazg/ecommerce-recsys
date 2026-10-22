"""Export a small static showcase from verified, unchanged snapshot references."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, file_sha, inference_code
from ecommerce_recsys.artifacts.runtime import evidence_digest, load_bundle

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SHA256 = "84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe"
REFERENCE_POSITIONS = (0, 25, 50, 75, 100)
SOURCE_NAMES = frozenset(
    {"item_knn", "als", "category_popularity", "recent_popularity", "global_popularity"}
)


def exporter_sha() -> str:
    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def check_output_location(bundle_path: Path, output: Path) -> Path:
    resolved = output.resolve()
    if resolved.is_relative_to(bundle_path.resolve()):
        raise ValueError("Demo output must stay outside the immutable input bundle.")
    return resolved


def write_once(path: Path, payload: dict) -> None:
    """Publish complete UTF-8 bytes without replacing an existing output."""
    raw = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def public_item(candidate, retrieval_rank: int, categories: dict) -> dict:
    if not isinstance(candidate.item_id, str) or not re.fullmatch(
        r"[0-9]{1,16}", candidate.item_id
    ):
        raise ValueError("Retailrocket item codes must be decimal strings.")
    category = categories.get(candidate.item_id)
    if category is not None and (
        not isinstance(category, str) or not re.fullmatch(r"[0-9]{1,16}", category)
    ):
        raise ValueError("Category must be an anonymous decimal code or null.")
    if type(retrieval_rank) is not int or not 1 <= retrieval_rank <= 1000:
        raise ValueError("Retrieval rank is outside the candidate budget.")
    if not math.isfinite(candidate.score):
        raise ValueError("Nonfinite candidate score.")
    sources = []
    for entry in candidate.evidence:
        if (
            entry.source not in SOURCE_NAMES
            or type(entry.rank) is not int
            or not 1 <= entry.rank <= 1000
            or not math.isfinite(entry.score)
        ):
            raise ValueError("Invalid retrieval evidence.")
        sources.append({"source": entry.source, "rank": entry.rank})
    if not sources or len({entry["source"] for entry in sources}) != len(sources):
        raise ValueError("Missing or duplicate source evidence.")
    return {
        "item_id": candidate.item_id,
        "category_id": category,
        "retrieval_rank": retrieval_rank,
        "sources": sorted(sources, key=lambda entry: entry["source"]),
    }


def build_profiles(bundle, references: list[dict]) -> list[dict]:
    """Allowlist public fields; never serialize a private reference or user object."""
    if len(references) != 101 or [r["trace"]["route"] for r in references] != (
        ["hybrid_learned"] * 100 + ["recent_popularity"]
    ):
        raise ValueError("Expected the sealed 100-warm/one-cold reference inventory.")
    profiles = []
    for ordinal, position in enumerate(REFERENCE_POSITIONS, 1):
        reference = references[position]
        user = reference["user_id"]
        trace = bundle.trace(user)
        if digest(trace) != digest(reference["trace"]):
            raise ValueError("Loaded output/trace differs from the sealed reference.")
        context = bundle.context(user)
        warm = trace["route"] == "hybrid_learned"
        if warm != (user in bundle.user_index) or (not warm and user is not None):
            raise ValueError("Reference route and snapshot context differ.")
        pool = (bundle.hybrid if warm else bundle.cold).generate(context, 1000)
        ids = [candidate.item_id for candidate in pool]
        if (
            not ids
            or len(ids) > 1000
            or len(set(ids)) != len(ids)
            or ids != trace["pool"]
            or evidence_digest(pool) != trace["evidence_sha256"]
            or set(ids) & set(context.history)
            or not set(ids).issubset(bundle.items)
        ):
            raise ValueError("Candidate inventory, eligibility or evidence differs.")
        output = trace["output"]
        if (
            len(output) != min(20, len(ids))
            or len(set(output)) != len(output)
            or not set(output).issubset(ids)
        ):
            raise ValueError("Invalid Top-20 reference output.")
        orders = {"learned": output, "rrf": ids[:20]} if warm else {"recent": output}
        shown = set(item for order in orders.values() for item in order)
        profiles.append(
            {
                "id": f"profile-{ordinal:02d}" if warm else "cold-start",
                "label": f"Snapshot profile {ordinal:02d}" if warm else "First visit",
                "cohort": "warm" if warm else "cold",
                "route": trace["route"],
                "history_items": len(context.history),
                "candidate_count": len(ids),
                "orders": orders,
                "items": [
                    public_item(candidate, rank, bundle.features.categories)
                    for rank, candidate in enumerate(pool, 1)
                    if candidate.item_id in shown
                ],
            }
        )
    return profiles


def export(bundle_path: Path, output: Path) -> dict:
    output_location = check_output_location(bundle_path, output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Showcase output already exists; use a fresh version/path.")
    source_before = exporter_sha()
    implementation_before = inference_code()
    bundle = load_bundle(bundle_path, expected_manifest_sha256=MANIFEST_SHA256)
    references_path = bundle_path / "references.json"
    reference_sha = file_sha(references_path)
    if reference_sha != bundle.manifest["components"]["references.json"]["sha256"]:
        raise ValueError("Sealed references changed after bundle verification.")
    references = json.loads(references_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "mode": "precomputed_model_outputs",
        "model": {
            "version": bundle.manifest["bundle_version"],
            "manifest_sha256": MANIFEST_SHA256,
            "cutoff_ms": bundle.manifest["snapshot"]["cutoff"],
            "fold": bundle.manifest["snapshot"]["fold_index"],
        },
        "provenance": {
            "exporter_sha256_lf": source_before,
            "inference_code_sha256": implementation_before,
            "sealed_references_sha256": reference_sha,
            "selection": "fixed reference positions 0,25,50,75 plus cold; no target inspection",
            "reference_trace_parity": True,
            "examples": 5,
            "quality_recomputed": False,
            "live_inference": False,
        },
        "profiles": build_profiles(bundle, references),
    }
    if (
        exporter_sha() != source_before
        or inference_code() != implementation_before
        or file_sha(bundle_path / "model_manifest.json") != MANIFEST_SHA256
        or file_sha(references_path) != reference_sha
    ):
        raise ValueError("Export inputs or implementation changed while running.")
    payload["content_sha256"] = digest(payload)
    if check_output_location(bundle_path, output) != output_location:
        raise ValueError("Demo output location changed while exporting.")
    write_once(output_location, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = export(args.bundle, args.output)
    print(f"Verified {len(payload['profiles'])} static examples; no live service started.")


if __name__ == "__main__":
    main()
