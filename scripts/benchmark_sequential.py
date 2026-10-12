"""Select and measure train-time transition retrieval on rolling warm targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from time import perf_counter

import pandas as pd

from ecommerce_recsys.data.rolling_provenance import (
    manifest_fingerprint,
    sha256_file,
    verify_fold_files,
)
from ecommerce_recsys.evaluation.candidates import CandidateMetrics, validate_targets
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.retrieval.sequential import TransitionTable, histories_for_users

LOOKBACKS = (5, 20)
DECAYS = (0.5, 0.8)
N_VALUES = (100, 500, 1000)
CONFIGS = {
    **{
        f"ordered_h{history}_d{str(decay).replace('.', '')}": {
            "lookback": history,
            "decay": decay,
        }
        for history in LOOKBACKS
        for decay in DECAYS
    },
    **{f"equal_h{history}": {"lookback": history, "decay": None} for history in LOOKBACKS},
}
POLICY = {
    "version": 1,
    "cohort": "warm first unseen target, all targets in denominator",
    "transition": "adjacent distinct timestamp buckets; all distinct cross-bucket item pairs except self",
    "same_timestamp": "one unordered bucket; no within-bucket transition or order",
    "score": "mean source-to-destination transition probability per bucket; sum weighted buckets",
    "seen_filter": "entire train-time user history, no fallback",
    "configs": CONFIGS,
    "candidate_budgets": list(N_VALUES),
    "development_folds": [1, 2, 3, 4],
    "diagnostic_folds": [5, 6, 7, 8, 9],
    "selection": "ordered pooled integer hits@100, hits@1000, smaller H, smaller decay; equal control at same H",
    "tie_break": "descending score, ascending string item ID",
    "numeric_threads": 1,
    "blind_holdout": False,
}


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = (
        "scripts/benchmark_sequential.py",
        "src/ecommerce_recsys/retrieval/sequential.py",
        "src/ecommerce_recsys/retrieval/base.py",
        "src/ecommerce_recsys/evaluation/candidates.py",
        "src/ecommerce_recsys/evaluation/latency.py",
        "src/ecommerce_recsys/data/splitting.py",
        "src/ecommerce_recsys/data/rolling_provenance.py",
        "src/ecommerce_recsys/evaluation/numeric_threads.py",
        "pyproject.toml",
    )
    value = hashlib.sha256()
    for relative in paths:
        path = root / relative
        value.update(relative.encode())
        value.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return value.hexdigest()


def write_artifact(path: Path, payload: dict) -> None:
    payload["payload_sha256"] = digest(
        {key: value for key, value in payload.items() if key != "payload_sha256"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def read_artifact(path: Path, expected: dict) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if any(artifact.get(key) != value for key, value in expected.items()) or artifact.get(
        "payload_sha256"
    ) != digest({key: value for key, value in artifact.items() if key != "payload_sha256"}):
        raise ValueError("Sequential artifact provenance or payload differs from the current run.")
    return artifact


def inputs(args: argparse.Namespace, *, max_fold: int) -> tuple[dict, dict]:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest_sha = manifest_fingerprint(manifest)
    if sha256_file(args.input_path) != manifest["source_sha256"]:
        raise ValueError("Processed interactions differ from the rolling manifest.")
    verify_fold_files(manifest, args.fold_dir, max_fold)
    identity = {
        "manifest_sha256": manifest_sha,
        "source_sha256": manifest["source_sha256"],
        "code_sha256": code_fingerprint(),
        "policy": POLICY,
        "runtime": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
        },
    }
    return manifest, identity


def _validate_rows(rows: list[dict], manifest: dict, *, phase: str) -> None:
    first = 1 if phase == "development" else 5
    maximum = 4 if phase == "development" else 5
    if len(rows) > maximum or [row.get("fold_index") for row in rows] != list(
        range(first, first + len(rows))
    ):
        raise ValueError("Sequential artifact has invalid or duplicate fold order.")
    for row in rows:
        fold = manifest["folds"][row["fold_index"] - 1]
        if (
            row.get("requests") != fold["warm_target_users"]
            or row.get("cutoff") != fold["train_cutoff"]
            or row.get("catalog_items") != fold["train_catalog_items"]
        ):
            raise ValueError(
                "Sequential artifact counts, catalog or cutoff differ from the manifest."
            )
        names = set(row["configs"])
        if (phase == "development" and names != set(CONFIGS)) or (
            phase == "diagnostic" and (len(names) != 2 or not names.issubset(CONFIGS))
        ):
            raise ValueError("Sequential artifact contains an invalid configuration grid.")
        if not math.isfinite(row["fit_seconds"]) or row["fit_seconds"] < 0:
            raise ValueError("Sequential artifact contains invalid fit cost.")
        for result in row["configs"].values():
            if result["evaluation_users"] != row["requests"]:
                raise ValueError("Sequential configuration denominator differs from the manifest.")
            if not math.isfinite(result["retrieval_seconds"]) or result["retrieval_seconds"] < 0:
                raise ValueError("Sequential artifact contains invalid retrieval cost.")
            for n in N_VALUES:
                totals = result["totals"][str(n)]
                if not (
                    0 <= totals["hits"] <= result["reachable_targets"] <= row["requests"]
                    and 0 <= totals["candidate_count"] <= n * row["requests"]
                    and 0 <= totals["empty_requests"] <= row["requests"]
                    and 0 <= totals["full_requests"] <= row["requests"]
                    and 0 <= totals["unique_items"] <= fold["train_catalog_items"]
                ):
                    raise ValueError("Sequential artifact metrics exceed their bounds.")
                if not math.isclose(
                    result["metrics"][f"Recall@{n}"],
                    totals["hits"] / row["requests"],
                    rel_tol=0,
                    abs_tol=1e-12,
                ):
                    raise ValueError(
                        "Sequential artifact recall differs from its integer numerator."
                    )


def validate_completion(artifact: dict, *, phase: str) -> None:
    required = 4 if phase == "development" else 5
    if type(artifact.get("complete")) is not bool or artifact["complete"] != (
        len(artifact["folds"]) == required
    ):
        raise ValueError("Sequential completion flag disagrees with fold count.")


def evaluate_fold(
    *,
    fold: dict,
    interactions: pd.DataFrame,
    fold_dir: Path,
    names: tuple[str, ...],
) -> dict:
    if any(
        type(fold[key]) is not int for key in ("fold_index", "train_cutoff", "evaluation_cutoff")
    ):
        raise ValueError("Sequential fold index and cutoffs must be plain integers.")
    cutoff = fold["train_cutoff"]
    evaluation_cutoff = fold["evaluation_cutoff"]
    if cutoff >= evaluation_cutoff:
        raise ValueError("Sequential evaluation cutoff must follow its training cutoff.")
    train = interactions.loc[interactions["timestamp"] <= cutoff]
    targets = pd.read_parquet(fold_dir / "warm_targets.parquet")
    catalog = pd.read_parquet(fold_dir / "items_train.parquet")
    if len(train) != fold["training_interactions"] or len(targets) != fold["warm_target_users"]:
        raise ValueError("Sequential fold counts differ from rolling manifest.")
    if catalog["item_id"].isna().any() or catalog["item_id"].astype(str).duplicated().any():
        raise ValueError("Sequential catalog contains null or duplicate IDs.")
    if (
        not pd.api.types.is_integer_dtype(targets["timestamp"])
        or not ((targets["timestamp"] > cutoff) & (targets["timestamp"] <= evaluation_cutoff)).all()
    ):
        raise ValueError("Sequential target crosses the evaluation window.")
    validate_targets(train, targets, "warm")
    catalog_ids = frozenset(catalog["item_id"].astype(str))
    if len(catalog_ids) != fold["train_catalog_items"]:
        raise ValueError("Sequential catalog size differs from rolling manifest.")
    started = perf_counter()
    table = TransitionTable.fit(train, catalog_ids, cutoff)
    fit_seconds = perf_counter() - started
    histories = histories_for_users(train, targets["user_id"].astype(str), cutoff)
    counters = {name: CandidateMetrics(catalog_ids, N_VALUES) for name in names}
    seconds = {name: 0.0 for name in names}
    for index, target in enumerate(targets.itertuples(index=False), start=1):
        user = str(target.user_id)
        history = histories[user]
        for name in names:
            started = perf_counter()
            pool = table.generate(history, max(N_VALUES), **CONFIGS[name])
            seconds[name] += perf_counter() - started
            if any(candidate.item_id not in catalog_ids for candidate in pool):
                raise ValueError("Sequential source returned a catalog-ineligible item.")
            counters[name].add(str(target.item_id), pool)
        if index % 1000 == 0 or index == len(targets):
            print(f"  sequential fold {fold['fold_index']}: {index:,}/{len(targets):,}", flush=True)
    return {
        "fold_index": fold["fold_index"],
        "cutoff": cutoff,
        "requests": len(targets),
        "catalog_items": len(catalog_ids),
        "transition_observations": table.observations,
        "distinct_transition_pairs": table.distinct_pairs,
        "train_timestamp_buckets": table.train_buckets,
        "fit_seconds": fit_seconds,
        "configs": {
            name: {**counter.output(), "retrieval_seconds": seconds[name]}
            for name, counter in counters.items()
        },
    }


def select_ordered(rows: list[dict]) -> tuple[str, str]:
    if [row["fold_index"] for row in rows] != [1, 2, 3, 4] or any(
        set(row["configs"]) != set(CONFIGS) for row in rows
    ):
        raise ValueError("Sequential selection requires the full development grid on folds 1–4.")
    ordered = [name for name in CONFIGS if name.startswith("ordered_")]

    def key(name: str) -> tuple[int, int, int, float]:
        return (
            sum(row["configs"][name]["totals"]["100"]["hits"] for row in rows),
            sum(row["configs"][name]["totals"]["1000"]["hits"] for row in rows),
            -CONFIGS[name]["lookback"],
            -CONFIGS[name]["decay"],
        )

    selected = max(ordered, key=key)
    return selected, f"equal_h{CONFIGS[selected]['lookback']}"


def _development(args: argparse.Namespace) -> None:
    manifest, identity = inputs(args, max_fold=4)
    expected = {"benchmark": "sequential-development-v1", **identity}
    if args.development_artifact.exists():
        artifact = read_artifact(args.development_artifact, expected)
        _validate_rows(artifact["folds"], manifest, phase="development")
        validate_completion(artifact, phase="development")
    else:
        artifact = {**expected, "folds": [], "complete": False}
    interactions = pd.read_parquet(args.input_path, columns=["user_id", "item_id", "timestamp"])
    for fold in manifest["folds"][:4]:
        if fold["fold_index"] <= len(artifact["folds"]):
            continue
        row = evaluate_fold(
            fold=fold,
            interactions=interactions,
            fold_dir=args.fold_dir / f"fold_{fold['fold_index']:02d}",
            names=tuple(CONFIGS),
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == 4
        if artifact["complete"]:
            artifact["selected_ordered"], artifact["selected_control"] = select_ordered(
                artifact["folds"]
            )
        write_artifact(args.development_artifact, artifact)
        print(f"Saved development fold {fold['fold_index']}", flush=True)


def require_lock(args: argparse.Namespace, manifest: dict, identity: dict) -> tuple[str, str]:
    development = read_artifact(
        args.development_artifact, {"benchmark": "sequential-development-v1", **identity}
    )
    _validate_rows(development["folds"], manifest, phase="development")
    if not development.get("complete") or len(development["folds"]) != 4:
        raise ValueError("Sequential development grid is incomplete.")
    selected = select_ordered(development["folds"])
    if (development.get("selected_ordered"), development.get("selected_control")) != selected:
        raise ValueError("Sequential development selection differs from the frozen rule.")
    lock = read_artifact(
        args.selection_lock,
        {
            "benchmark": "sequential-selection-lock-v1",
            **identity,
            "development_artifact_sha256": sha256_file(args.development_artifact),
            "selected_ordered": selected[0],
            "selected_control": selected[1],
        },
    )
    if lock.get("role") != "locked development choice; later folds are post-selection diagnostics":
        raise ValueError("Sequential selection lock has an unexpected role.")
    return selected


def _lock(args: argparse.Namespace) -> None:
    manifest, identity = inputs(args, max_fold=4)
    development = read_artifact(
        args.development_artifact, {"benchmark": "sequential-development-v1", **identity}
    )
    _validate_rows(development["folds"], manifest, phase="development")
    if not development.get("complete") or len(development["folds"]) != 4:
        raise ValueError("Sequential selection requires all four development folds.")
    ordered, control = select_ordered(development["folds"])
    if (development.get("selected_ordered"), development.get("selected_control")) != (
        ordered,
        control,
    ):
        raise ValueError("Sequential development selection differs from the frozen rule.")
    payload = {
        "benchmark": "sequential-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "selected_ordered": ordered,
        "selected_control": control,
        "role": "locked development choice; later folds are post-selection diagnostics",
    }
    if args.selection_lock.exists():
        read_artifact(args.selection_lock, payload)
    else:
        write_artifact(args.selection_lock, payload)
    print(f"Locked {ordered} against {control}", flush=True)


def _diagnostic(args: argparse.Namespace) -> None:
    if not 5 <= args.max_fold <= 9:
        raise ValueError("Sequential diagnostic max fold must be within 5–9.")
    manifest, identity = inputs(args, max_fold=args.max_fold)
    ordered, control = require_lock(args, manifest, identity)
    expected = {
        "benchmark": "sequential-diagnostic-v1",
        **identity,
        "selection_lock_sha256": sha256_file(args.selection_lock),
        "selected_ordered": ordered,
        "selected_control": control,
    }
    if args.diagnostic_artifact.exists():
        artifact = read_artifact(args.diagnostic_artifact, expected)
        _validate_rows(artifact["folds"], manifest, phase="diagnostic")
        validate_completion(artifact, phase="diagnostic")
        if any(set(row["configs"]) != {ordered, control} for row in artifact["folds"]):
            raise ValueError("Sequential diagnostic artifact mixes configurations.")
    else:
        artifact = {
            **expected,
            "role": "post-selection diagnostic; not blind validation",
            "folds": [],
            "complete": False,
        }
    interactions = pd.read_parquet(args.input_path, columns=["user_id", "item_id", "timestamp"])
    for fold in manifest["folds"][4 : args.max_fold]:
        if fold["fold_index"] < 5 + len(artifact["folds"]):
            continue
        row = evaluate_fold(
            fold=fold,
            interactions=interactions,
            fold_dir=args.fold_dir / f"fold_{fold['fold_index']:02d}",
            names=(ordered, control),
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == 5
        write_artifact(args.diagnostic_artifact, artifact)
        print(f"Saved diagnostic fold {fold['fold_index']}", flush=True)


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("development", "lock", "diagnostic"))
    parser.add_argument(
        "--input-path", type=Path, default=Path("data/processed/interactions.parquet")
    )
    parser.add_argument("--fold-dir", type=Path, default=Path("data/rolling"))
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/rolling/manifest.json"))
    parser.add_argument(
        "--development-artifact",
        type=Path,
        default=Path("benchmarks/retrieval/sequential_development_v1.json"),
    )
    parser.add_argument(
        "--selection-lock",
        type=Path,
        default=Path("benchmarks/retrieval/sequential_selection_lock_v1.json"),
    )
    parser.add_argument(
        "--diagnostic-artifact",
        type=Path,
        default=Path("benchmarks/retrieval/sequential_diagnostic_v1.json"),
    )
    parser.add_argument("--max-fold", type=int, default=9)
    args = parser.parse_args()
    if args.phase == "development":
        _development(args)
    elif args.phase == "lock":
        _lock(args)
    else:
        _diagnostic(args)


if __name__ == "__main__":
    main()
