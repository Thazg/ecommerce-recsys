"""Verify completed offline evidence and record its seed and feature-audit provenance."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

from ecommerce_recsys.data.rolling_provenance import sha256_file

if __package__:
    from scripts import benchmark_model_policy as runner
else:
    import benchmark_model_policy as runner


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def seed_record(source: Path, ranker_development: dict) -> dict[str, int]:
    """Extract the fit seed from the already fingerprinted source, not new defaults."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    values = [
        ast.literal_eval(keyword.value)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "MatrixFactorizationRecommender"
        for keyword in call.keywords
        if keyword.arg == "random_state"
    ]
    negative_seed = ranker_development["policy"]["negative_sampling"]["seed"]
    if (
        len(values) != 1
        or any(type(value) is not int or value < 0 for value in (*values, negative_seed))
        or negative_seed != runner.ranker.POLICY["negative_sampling"]["seed"]
    ):
        raise ValueError("Bound source and ranker artifact have invalid or inconsistent seeds.")
    return {"als_fit": values[0], "ranker_negative_sampling": negative_seed}


def verify_feature_audit(path: Path, quality_path: Path, quality: dict, verifier: Path) -> None:
    """Verify the earlier independent scan against the same hash-verified Parquet."""
    audit = json.loads(path.read_text(encoding="utf-8"))
    rows = audit.get("folds", [])
    payload = hashlib.sha256(
        json.dumps(rows, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    if (
        audit.get("benchmark") != "m10-ranking-feature-audit"
        or audit.get("quality_sha256") != sha256_file(quality_path)
        or audit.get("verifier_sha256") != normalized_sha256(verifier)
        or audit.get("payload_sha256") != payload
        or [row["fold_index"] for row in rows] != [1, 2, 3, 4]
        or [row["fold_index"] for row in quality["folds"]] != [1, 2, 3, 4]
    ):
        raise ValueError("Feature audit identity, payload or development fold coverage differs.")
    for row, expected in zip(rows, quality["folds"], strict=True):
        for name in ("requests", "candidates", "positives", "requests_sha256", "candidates_sha256"):
            if row[name] != expected[name] or (
                name in {"requests", "candidates", "positives"} and type(row[name]) is not int
            ):
                raise ValueError("Feature audit counts or file hashes differ from ranking data.")
        for name in ("null_feature_values", "nonfinite_numeric_values"):
            if type(row[name]) is not int or row[name] != 0:
                raise ValueError("Feature audit reports null or nonfinite features.")


def runner_args(data_dir: Path, benchmark_dir: Path) -> argparse.Namespace:
    paths = {
        "input_path": data_dir / "processed/interactions.parquet",
        "fold_dir": data_dir / "rolling",
        "ranking_data_dir": data_dir / "ranking/m10_v1",
        "manifest": benchmark_dir / "rolling/manifest.json",
        "sweep_dir": benchmark_dir / "rolling",
        "reference": benchmark_dir / "retrieval/candidates.json",
        "ranking_quality": benchmark_dir / "ranking/m10_quality_v1.json",
        "ranker_development": benchmark_dir / "ranking/ranker_development_v1.json",
        "ranker_lock": benchmark_dir / "ranking/ranker_selection_lock_v1.json",
        "ranker_diagnostic": benchmark_dir / "ranking/ranker_diagnostic_v1.json",
        "diversity_development": benchmark_dir / "ranking/diversity_development_v1.json",
        "diversity_lock": benchmark_dir / "ranking/diversity_selection_lock_v1.json",
        "diversity_diagnostic": benchmark_dir / "ranking/diversity_diagnostic_v1.json",
        "development_artifact": benchmark_dir / "model_policy/development_v1.json",
        "selection_lock": benchmark_dir / "model_policy/selection_lock_v1.json",
        "diagnostic_artifact": benchmark_dir / "model_policy/diagnostic_v1.json",
    }
    return argparse.Namespace(phase="diagnostic", max_fold=9, **paths)


def build_provenance(data_dir: Path, benchmark_dir: Path) -> dict:
    args = runner_args(data_dir, benchmark_dir)
    manifest, configs, identity, _, quality, ranker_identity, ranker_dev, _ = runner.inputs(args, 9)
    lock = runner.require_lock(args, identity, manifest)
    model, _ = runner.diversity.locked_ranker_model(runner.upstream_args(args), ranker_identity)
    diagnostic = runner.read_artifact(
        args.diagnostic_artifact,
        {
            "benchmark": "model-policy-diagnostic-v1",
            **identity,
            "selection_lock_sha256": sha256_file(args.selection_lock),
            "selected_routes": lock["selected_routes"],
            "ranker_diagnostic_sha256": sha256_file(args.ranker_diagnostic),
            "diversity_diagnostic_sha256": sha256_file(args.diversity_diagnostic),
            "ranker_model_sha256": runner.digest(runner.model_record(model)),
        },
    )
    runner.validate_completion(diagnostic, manifest, "diagnostic")
    if not diagnostic["complete"]:
        raise ValueError("Provenance verification requires complete diagnostic folds 5–9.")
    root = Path(__file__).resolve().parents[1]
    audit_path = benchmark_dir / "ranking/m10_feature_audit_v1.json"
    audit_verifier = root / "scripts/verify_ranking_dataset.py"
    verify_feature_audit(audit_path, args.ranking_quality, quality, audit_verifier)
    files = (
        "scripts/benchmark_model_policy.py",
        "src/ecommerce_recsys/evaluation/model_policy.py",
        "scripts/learned_ranker.py",
        "scripts/benchmark_candidates.py",
        "scripts/verify_ranking_dataset.py",
        "scripts/verify_model_policy.py",
    )
    record = {
        "benchmark": "model-policy-provenance-v1",
        "role": "retrospective verification supplement; not a pre-diagnostic lock or model bundle",
        "code_sha256": identity["code_sha256"],
        "source_sha256_lf": {path: normalized_sha256(root / path) for path in files},
        "artifact_sha256": {
            "development_v1.json": sha256_file(args.development_artifact),
            "selection_lock_v1.json": sha256_file(args.selection_lock),
            "diagnostic_v1.json": sha256_file(args.diagnostic_artifact),
        },
        "m10_feature_audit_sha256": sha256_file(audit_path),
        "m10_quality_sha256": sha256_file(args.ranking_quality),
        "seeds": seed_record(root / "scripts/benchmark_candidates.py", ranker_dev),
        "source_model_configs": configs,
        "selected_routes": lock["selected_routes"],
        "development_folds": [2, 3, 4],
        "diagnostic_folds": [row["fold_index"] for row in diagnostic["folds"]],
        "blind_holdout": False,
    }
    return {**record, "payload_sha256": runner.digest(record)}


def write_or_verify(path: Path, record: dict) -> None:
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != record:
            raise ValueError(
                "Existing provenance supplement differs; preserve it and use a new path."
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_bytes((json.dumps(record, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    pending.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--benchmark-dir", type=Path, default=Path("benchmarks"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    record = build_provenance(args.data_dir, args.benchmark_dir)
    path = args.output or args.benchmark_dir / "model_policy/provenance_v1.json"
    write_or_verify(path, record)
    print(f"Verified completed model-policy evidence and provenance supplement: {path}")


if __name__ == "__main__":
    main()
