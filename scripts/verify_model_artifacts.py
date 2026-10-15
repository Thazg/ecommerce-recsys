"""Load an immutable snapshot and verify its label-free producer references."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.contract import (
    digest,
    environment,
    file_sha,
    inference_code,
    runtime_code,
    write_json,
)


def verify_references(bundle, path: Path) -> int:
    records = json.loads((path / "references.json").read_text(encoding="utf-8"))
    if not records or not isinstance(records, list):
        raise ValueError("Producer references must be a nonempty list.")
    seen = set()
    for record in records:
        user = record["user_id"]
        if user in seen or bundle.trace(user) != record["trace"]:
            raise ValueError(
                "Loaded evidence/features/scores/output differs from producer reference."
            )
        seen.add(user)
    if None not in seen or not any(user in bundle.user_index for user in seen):
        raise ValueError("Producer references must cover warm and cold contexts.")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--quality-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = perf_counter()
    bundle = load_bundle(args.bundle, expected_manifest_sha256=args.manifest_sha256)
    loaded = perf_counter() - started
    count = verify_references(bundle, args.bundle)
    record = {
        "verification": "offline-bundle-loader-v1",
        "bundle_version": bundle.manifest["bundle_version"],
        "manifest_sha256": file_sha(args.bundle / "model_manifest.json"),
        "load_seconds": loaded,
        "reference_requests": count,
        "parity": True,
        "producer_runtime_code_sha256": bundle.manifest["runtime_code_sha256"],
        "loader_runtime_code_sha256": runtime_code(),
        "inference_code_sha256": inference_code(),
        "verifier_sha256_lf": hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "runtime": environment(),
        "quality_recomputed": False,
    }
    if args.quality_receipt:
        source = json.loads(args.quality_receipt.read_text(encoding="utf-8"))
        if (
            source.get("artifact") != "offline-model-bundle-validation-v1"
            or source.get("complete") is not True
            or source.get("loaded_quality_matches_policy") is not True
            or source.get("bundle_version") != record["bundle_version"]
            or source.get("payload_sha256")
            != digest({key: value for key, value in source.items() if key != "payload_sha256"})
            or source.get("identity", {}).get("manifest_sha256") != record["manifest_sha256"]
            or source.get("components") != bundle.manifest["components"]
        ):
            raise ValueError("Quality receipt does not bind this immutable bundle.")
        record["source_quality_receipt_sha256"] = file_sha(args.quality_receipt)
    record["payload_sha256"] = digest(record)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            previous = json.loads(args.output.read_text(encoding="utf-8"))
            if previous.get("payload_sha256") != digest(
                {key: value for key, value in previous.items() if key != "payload_sha256"}
            ) or {
                key: value
                for key, value in previous.items()
                if key not in {"load_seconds", "payload_sha256"}
            } != {
                key: value
                for key, value in record.items()
                if key not in {"load_seconds", "payload_sha256"}
            }:
                raise ValueError(
                    "Loader receipt differs; preserve it and choose a new output path."
                )
        else:
            write_json(args.output, record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
