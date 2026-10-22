"""Check static-demo receipt, current source and export identity without loading a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, inference_code

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe"
FILES = (
    "README.md",
    "demo/app.js",
    "demo/data/showcase_v1.json",
    "demo/favicon.svg",
    "demo/index.html",
    "demo/schema.mjs",
    "demo/styles.css",
    "demo/transport.mjs",
    "docs/ARCHITECTURE_CURRENT.md",
    "docs/DECISIONS.md",
    "docs/DEPLOYMENT_DESIGN.md",
    "docs/PROJECT_STATUS.md",
    "docs/SNAPSHOT_EXPLORER.md",
    "scripts/export_snapshot_demo.py",
    "scripts/verify_snapshot_demo.py",
    "tests/unit/test_snapshot_demo.py",
    "tests/unit/test_snapshot_demo_verification.py",
    "tests/web/test_snapshot_demo.mjs",
)


def bounded_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("Expected a bounded regular demo file.")
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024**2 + 1)
    if len(raw) > 4 * 1024**2:
        raise ValueError("Demo file exceeds the verification byte budget.")
    return raw


def file_digest(path: Path) -> str:
    return hashlib.sha256(bounded_bytes(path).replace(b"\r\n", b"\n")).hexdigest()


def read_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON value.")

    try:
        value = json.loads(
            bounded_bytes(path).decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid
        )
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object.")
        pin = value.get("content_sha256")
        if not isinstance(pin, str) or not re.fullmatch(r"[a-f0-9]{64}", pin):
            raise ValueError("Missing content digest.")
        if digest({k: v for k, v in value.items() if k != "content_sha256"}) != pin:
            raise ValueError("Demo content checksum differs.")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid demo JSON.") from exc


def verify(root: Path, receipt_path: Path) -> dict:
    receipt = read_json(receipt_path)
    if (
        type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or receipt.get("verification") != "local-static-snapshot-explorer-v1"
        or receipt.get("model_manifest_sha256") != MANIFEST
        or any(
            receipt.get(key) is not False
            for key in ("live_inference", "cloud_deployed", "deployment_eligible")
        )
    ):
        raise ValueError("Unsupported demo receipt identity or scope.")
    pins = receipt.get("files_sha256_lf")
    if not isinstance(pins, dict) or set(pins) != set(FILES):
        raise ValueError("Demo source inventory is incomplete or foreign.")
    root = root.resolve()
    public_files = {name for name in FILES if name.startswith("demo/")}
    public_dirs = {str(Path(name).parent).replace("\\", "/") for name in public_files}
    for target in (root / "demo").rglob("*"):
        name = target.relative_to(root).as_posix()
        if target.is_symlink() or (name not in (public_dirs if target.is_dir() else public_files)):
            raise ValueError("Unexpected file or directory in the public demo inventory.")
    for name in FILES:
        target = root / name
        if (
            not target.resolve().is_relative_to(root)
            or any(
                part.is_symlink()
                for part in (target, *target.parents)
                if part != root and part.is_relative_to(root)
            )
            or not isinstance(pins[name], str)
            or not re.fullmatch(r"[a-f0-9]{64}", pins[name])
            or file_digest(target) != pins[name]
        ):
            raise ValueError(f"Demo source fingerprint differs: {name}")
    data = read_json(root / "demo/data/showcase_v1.json")
    provenance = data.get("provenance", {})
    if (
        not isinstance(provenance, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data["content_sha256"] != receipt.get("export_content_sha256")
        or data.get("mode") != "precomputed_model_outputs"
        or data.get("model")
        != {
            "version": "retailrocket-fold09-v1",
            "manifest_sha256": MANIFEST,
            "cutoff_ms": 1441216678608,
            "fold": 9,
        }
        or provenance.get("exporter_sha256_lf") != pins["scripts/export_snapshot_demo.py"]
        or provenance.get("inference_code_sha256") != inference_code()
        or provenance.get("reference_trace_parity") is not True
        or provenance.get("quality_recomputed") is not False
        or provenance.get("live_inference") is not False
        or type(provenance.get("examples")) is not int
        or provenance["examples"] != 5
        or not isinstance(data.get("profiles"), list)
        or len(data["profiles"]) != 5
    ):
        raise ValueError("Demo export provenance differs from the current implementation.")
    # No fit/load/trace calls: this checks recorded identity, not fresh model parity.
    return {"identity_verified": True, "files": len(FILES), "model_quality_recomputed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", type=Path, required=True, help="Receipt to verify against this checkout"
    )
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, args.check)))


if __name__ == "__main__":
    main()
