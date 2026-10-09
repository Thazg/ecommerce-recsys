"""Verify a complete candidate artifact without fitting or accessing raw data.

Run from the repository root: python -m scripts.verify_candidate_artifact
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from ecommerce_recsys.data.rolling_provenance import manifest_fingerprint, sha256_file
from ecommerce_recsys.evaluation.candidates import N_VALUES, summarize_candidates
from scripts.benchmark_candidates import (
    GENERATORS,
    POLICY,
    implementation_fingerprint,
    validate_checkpoint,
)

M7_SOURCE_COMMIT = "2fb4fd7545fd5f5dc5f0426b5ee37bcd28ff0ccb"
M7_SOURCE_SNAPSHOT_SHA256 = "27157b84ccf98306b23eb77d0526c09a1ea05c6da60e7468b0f4091f847b4cbe"
M7_IMPLEMENTATION_SHA256 = "d6e2c716cbf035586612e47dd8be45e674d6ed65e0c17892f6b91d8f9b117218"


def source_snapshot() -> dict:
    """Canonical LF hashes of public Python sources, tests and configuration."""
    root = Path(__file__).resolve().parents[1]
    paths = [root / "pyproject.toml", root / ".gitattributes"]
    for directory in ("src", "scripts", "tests"):
        paths.extend((root / directory).rglob("*.py"))
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in sorted(paths, key=lambda path: path.relative_to(root).as_posix())
    }
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"normalization": "LF line endings", "files_sha256": files, "sha256": digest}


def source_snapshot_at_commit(commit: str, expected_files: dict[str, str]) -> dict:
    """Read the immutable M7 source snapshot from Git, independent of M8 files."""
    root = Path(__file__).resolve().parents[1]
    resolved = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"{commit}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if resolved != M7_SOURCE_COMMIT:
        raise ValueError("M7 source commit does not match the published artifact anchor.")
    files = {}
    for relative in sorted(expected_files):
        raw = subprocess.run(
            ["git", "-C", str(root), "show", f"{resolved}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
        files[relative] = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"normalization": "LF line endings", "files_sha256": files, "sha256": digest}


def verify(artifact: dict, manifest: dict, *, source_proof: dict | None = None) -> dict:
    """Verify native fingerprints or a published canonical source snapshot.

    Benchmark resume keeps its strict native-byte check. Published verification
    also supports Git's line-ending conversion, using the complete LF-normalized
    source/configuration snapshot bound to the result file.
    """
    implementation = implementation_fingerprint()
    if source_proof is not None:
        if (
            source_proof["implementation_sha256"] != artifact["implementation_sha256"]
            or source_proof["implementation_sha256"] != M7_IMPLEMENTATION_SHA256
        ):
            raise ValueError("Published source identity differs from the M7 artifact anchor.")
        if source_proof["source_snapshot"].get(
            "sha256"
        ) != M7_SOURCE_SNAPSHOT_SHA256 or source_proof[
            "source_snapshot"
        ] != source_snapshot_at_commit(
            M7_SOURCE_COMMIT, source_proof["source_snapshot"]["files_sha256"]
        ):
            raise ValueError("Published source identity differs from the current checkout.")
        implementation = source_proof["implementation_sha256"]
    if [fold["fold_index"] for fold in manifest["folds"]] != list(range(1, 10)):
        raise ValueError("The complete M7 benchmark requires nine ordered folds.")
    expected = {
        "protocol_version": manifest["protocol_version"],
        "source_sha256": manifest["source_sha256"],
        "manifest_sha256": manifest_fingerprint(manifest),
        "implementation_sha256": implementation,
        "policy": POLICY,
        "cohorts": ["cold", "warm"],
    }
    validate_checkpoint(artifact, expected, manifest)
    rows = artifact["results"]
    required = {
        (fold["fold_index"], cohort, generator)
        for fold in manifest["folds"]
        for cohort in ("warm", "cold")
        for generator in GENERATORS
    }
    actual = {(r["fold_index"], r["cohort"], r["generator"]) for r in rows}
    if len(rows) != len(required) or actual != required:
        raise ValueError("Artifact requires complete fold/cohort/generator comparisons.")
    for row in rows:
        catalog_size = manifest["folds"][row["fold_index"] - 1]["train_catalog_items"]
        previous = 0
        for n in N_VALUES:
            total = row["totals"][str(n)]
            if total["hits"] < previous:
                raise ValueError("Hit totals must be monotonic across candidate budgets.")
            expected_rates = {
                f"Recall@{n}": total["hits"] / (row["evaluation_users"] or 1),
                f"reachable_recall@{n}": total["hits"] / (row["reachable_targets"] or 1),
                f"coverage@{n}": total["unique_items"] / (catalog_size or 1),
                f"mean_candidates@{n}": total["candidate_count"] / (row["evaluation_users"] or 1),
                f"empty_rate@{n}": total["empty_requests"] / (row["evaluation_users"] or 1),
                f"full_rate@{n}": total["full_requests"] / (row["evaluation_users"] or 1),
            }
            for key, value in expected_rates.items():
                if abs(row["metrics"][key] - value) > 1e-12:
                    raise ValueError(f"Metric {key} differs from its integer totals.")
            previous = total["hits"]
    for name, indices in (
        ("development_summary", range(1, 5)),
        ("post_selection_summary", range(5, 10)),
    ):
        if artifact[name] != summarize_candidates([r for r in rows if r["fold_index"] in indices]):
            raise ValueError(f"{name} differs from pooled integer totals.")
    return {
        "comparison_rows": len(rows),
        "folds": len(manifest["folds"]),
        "manifest_sha256": expected["manifest_sha256"],
        "implementation_sha256": expected["implementation_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact", type=Path, default=Path("benchmarks/retrieval/candidates.json")
    )
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument("--verification", type=Path)
    args = parser.parse_args()
    proof_path = args.verification or args.artifact.with_name("verification.json")
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else None
    if proof is not None and proof["result"]["file_sha256"] != sha256_file(args.artifact):
        raise ValueError("Published result bytes differ from the verification record.")
    result = verify(
        json.loads(args.artifact.read_text()),
        json.loads(args.manifest.read_text()),
        source_proof=proof,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
