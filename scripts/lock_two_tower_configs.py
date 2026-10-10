"""Lock Two-Tower model configurations from complete folds 1–4 development artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.benchmark_two_tower import (
    ALS_CONFIGS,
    POLICY,
    TWO_TOWER_CONFIGS,
    _canonical_sha256,
    _diagnostic_configs,
    _results_sha256,
    _runner_sha256,
)

LEGACY_ALS_RUNNER_SHA256 = "4c296e1044c2664d786ad9984592a9e8b139a9a47c514f9a0b56a7e2803b760c"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _select(path: Path, expected_model: str, configs: tuple[dict, ...]) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("model") != expected_model or artifact.get("phase") != "development":
        raise ValueError(f"Expected a {expected_model} development artifact.")
    if artifact.get("blind_holdout") is not False:
        raise ValueError(
            "Two-Tower lock requires folds 1–4 development results, not holdout results."
        )
    if (
        artifact.get("complete") is not True
        or artifact.get("expected_folds") != [1, 2, 3, 4]
        or artifact.get("completed_folds") != [1, 2, 3, 4]
    ):
        raise ValueError("Two-Tower lock requires a complete folds 1–4 development checkpoint.")
    if artifact.get("configurations") != list(configs):
        raise ValueError("Development artifact does not contain the complete predeclared grid.")
    expected_policy = POLICY.copy()
    expected_runner = _runner_sha256(Path(__file__).resolve().parents[1])
    reused_als = False
    if expected_model == "als":
        legacy_policy = POLICY.copy()
        legacy_policy["negative_sampling"] = (
            "independent uniform draws with replacement from train-catalog items first seen "
            "strictly before the positive timestamp; exclude encoded history and every "
            "same-timestamp item; skip examples with no eligible negative"
        )
        if artifact.get("policy") == legacy_policy:
            # The prior ALS measurements remain valid: MFRetriever reads the
            # unchanged deduplicated context.history field, and negative sampling
            # and ordered Two-Tower features do not participate in ALS.
            expected_policy = legacy_policy
            expected_runner = LEGACY_ALS_RUNNER_SHA256
            reused_als = True
    if artifact.get("policy") != expected_policy:
        raise ValueError("Development artifact does not use a recognized Two-Tower policy.")
    if artifact.get("policy_sha256") != _canonical_sha256(expected_policy):
        raise ValueError("Development artifact policy fingerprint is invalid.")
    if artifact.get("runner_sha256") != expected_runner:
        raise ValueError("Development artifact runner differs from the current implementation.")
    if artifact.get("results_sha256") != _results_sha256(artifact):
        raise ValueError("Development artifact result fingerprint is invalid.")
    hashes = (
        artifact.get("manifest_sha256"),
        artifact.get("input_sha256"),
        artifact.get("runner_sha256"),
        artifact.get("policy_sha256"),
    )
    if not artifact.get("runtime") or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in hashes
    ):
        raise ValueError("Development artifact is missing runtime or data provenance.")
    rows = artifact.get("results", [])
    required = {
        (json.dumps(config, sort_keys=True), fold) for config in configs for fold in range(1, 5)
    }
    observed = {
        (json.dumps(row["config"], sort_keys=True), row["fold_index"])
        for row in rows
        if row.get("phase") == "development" and row.get("fold_index") in range(1, 5)
    }
    if len(rows) != len(required) or observed != required:
        raise ValueError("Configuration lock requires the complete config × folds 1–4 grid.")
    candidates = []
    for config in configs:
        matched = [row for row in rows if row["config"] == config]
        users = sum(row["evaluation_users"] for row in matched)
        if users <= 0:
            raise ValueError("Development folds have no warm evaluation users.")
        hits_1000 = sum(row["totals"]["1000"]["hits"] for row in matched)
        hits_100 = sum(row["totals"]["100"]["hits"] for row in matched)
        if expected_model == "two_tower":
            complexity = (
                sum(row["model_cost"]["parameter_bytes"] for row in matched),
                config["max_history"],
                config["dimension"],
            )
        else:
            complexity = (
                config["factors"],
                config["iterations"],
                -config["regularization"],
            )
        candidates.append(
            ((-hits_1000, -hits_100, *complexity), config, users, hits_100, hits_1000)
        )
    _, selected, users, hits_100, hits_1000 = min(candidates, key=lambda item: item[0])
    return {
        "selected_config": selected,
        "development_user_windows": users,
        "development_hits_at_100": hits_100,
        "development_recall_at_100": hits_100 / users,
        "development_hits_at_1000": hits_1000,
        "development_recall_at_1000": hits_1000 / users,
        "tie_break": (
            "two-tower: lower summed parameter bytes, shorter history, lower dimension; "
            "ALS: fewer factors, fewer iterations, higher regularization"
        ),
        "development_artifact_sha256": file_sha256(path),
        "reused_legacy_als_artifact": reused_als,
        "manifest_sha256": artifact["manifest_sha256"],
        "input_sha256": artifact["input_sha256"],
        "policy_sha256": artifact["policy_sha256"],
        "runner_sha256": artifact["runner_sha256"],
        "runtime": artifact["runtime"],
    }


def _bind_als_diagnostic(path: Path, selection: dict) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    configs = list(_diagnostic_configs("als", selection["selected_config"]))
    expected_rows = {
        (json.dumps(config, sort_keys=True), fold) for config in configs for fold in range(5, 10)
    }
    observed_rows = {
        (json.dumps(row.get("config"), sort_keys=True), row.get("fold_index"))
        for row in artifact.get("results", [])
        if row.get("phase") == "diagnostic"
    }
    if (
        artifact.get("model") != "als"
        or artifact.get("phase") != "diagnostic"
        or artifact.get("complete") is not True
        or artifact.get("expected_folds") != [5, 6, 7, 8, 9]
        or artifact.get("completed_folds") != [5, 6, 7, 8, 9]
        or artifact.get("configurations") != configs
        or artifact.get("policy_sha256") != selection["policy_sha256"]
        or artifact.get("runner_sha256") != LEGACY_ALS_RUNNER_SHA256
        or artifact.get("development_artifact_sha256") != selection["development_artifact_sha256"]
        or artifact.get("manifest_sha256") != selection["manifest_sha256"]
        or artifact.get("input_sha256") != selection["input_sha256"]
        or artifact.get("runtime") != selection["runtime"]
        or artifact.get("results_sha256") != _results_sha256(artifact)
        or len(artifact.get("results", [])) != len(expected_rows)
        or observed_rows != expected_rows
    ):
        raise ValueError("ALS comparator diagnostic is incomplete or mismatched with its sweep.")
    return {
        "diagnostic_artifact_sha256": file_sha256(path),
        "diagnostic_runner_sha256": artifact["runner_sha256"],
        "diagnostic_policy_sha256": artifact["policy_sha256"],
        "diagnostic_selection_lock_sha256": artifact["selection_lock_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--two-tower", type=Path, required=True)
    parser.add_argument("--als", type=Path, required=True)
    parser.add_argument("--als-diagnostic", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/retrieval/m8_selection_lock_v1.json")
    )
    args = parser.parse_args()
    lock = {
        "protocol_version": "m8-rolling-v1",
        "selection_rule": "highest pooled Recall@1000 on folds 1–4; tie: Recall@100; then lower complexity",
        "blind_holdout": False,
        "selection_script_sha256": file_sha256(Path(__file__)),
        "two_tower": _select(args.two_tower, "two_tower", TWO_TOWER_CONFIGS),
        "als_candidate_recall": _select(args.als, "als", ALS_CONFIGS),
    }
    lock["als_candidate_recall"].update(
        _bind_als_diagnostic(args.als_diagnostic, lock["als_candidate_recall"])
    )
    if (
        lock["two_tower"]["manifest_sha256"] != lock["als_candidate_recall"]["manifest_sha256"]
        or lock["two_tower"]["input_sha256"] != lock["als_candidate_recall"]["input_sha256"]
        or lock["two_tower"]["runtime"] != lock["als_candidate_recall"]["runtime"]
    ):
        raise ValueError(
            "Two-tower and ALS artifacts must share the dataset, fold manifest and runtime; "
            "their model-specific policy and runner fingerprints are checked separately."
        )
    lock["policy_sha256"] = lock["two_tower"]["policy_sha256"]
    lock["runner_sha256"] = lock["two_tower"]["runner_sha256"]
    lock["runtime"] = lock["two_tower"]["runtime"]
    pending = args.output.with_suffix(args.output.suffix + ".tmp")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps(lock, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
