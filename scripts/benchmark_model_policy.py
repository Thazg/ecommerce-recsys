"""Compare and lock complete offline recommendation policies on rolling folds."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from collections import Counter
from pathlib import Path
from time import perf_counter

import implicit
import numpy as np
import pandas as pd

from ecommerce_recsys.data.rolling_provenance import sha256_file
from ecommerce_recsys.evaluation.candidates import validate_targets
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.evaluation.model_policy import (
    CANDIDATE_BUDGET,
    COLD_POLICIES,
    K_VALUES,
    WARM_POLICIES,
    PolicySpec,
    PolicyTotals,
    pooled_results,
    select_routes,
    validate_result,
)
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import (
    ABSENT_SOURCE_RANK,
    SOURCE_NAMES,
    SnapshotFeatures,
    request_id,
)
from ecommerce_recsys.ranking.diversity import category_novelty_order
from ecommerce_recsys.retrieval.base import Candidate, RetrievalContext
from ecommerce_recsys.retrieval.hybrid_candidates import HybridCandidateGenerator

if __package__:
    from scripts import benchmark_diversity as diversity
    from scripts import benchmark_ranker as ranker
    from scripts.benchmark_candidates import payload_fingerprint as candidate_payload_fingerprint
    from scripts.learned_ranker import PairwiseRanker, feature_matrix
else:
    import benchmark_diversity as diversity
    import benchmark_ranker as ranker
    from benchmark_candidates import payload_fingerprint as candidate_payload_fingerprint
    from learned_ranker import PairwiseRanker, feature_matrix

POLICY = {
    "version": 1,
    "warm_policies": [spec.record() for spec in WARM_POLICIES],
    "cold_policies": [spec.record() for spec in COLD_POLICIES],
    "candidate_budget": CANDIDATE_BUDGET,
    "output_budgets": list(K_VALUES),
    "development_folds": [2, 3, 4],
    "diagnostic_folds": [5, 6, 7, 8, 9],
    "ranker_alpha": 0.01,
    "ranker_training": "earlier labelled folds in development; frozen folds 1–4 model in diagnostic",
    "no_als_ranker": "unchanged full-hybrid trained model and schema; transfer, no pool-specific refit",
    "category_shortlist": 100,
    "category_bonus": 0.1,
    "selection": "separate warm/cold pooled hits@20, NDCG@20 sum, fewer sources, smaller bonus, policy name",
    "denominator": "all cohort user-windows, including catalog-unreachable and pool-missed targets",
    "warm_latency_requests": 100,
    "warm_latency_repetitions": 3,
    "cold_latency_repetitions": 100,
    "latency_sample": "ascending SHA-256 of fold:user; rotate fixed policy order by repetition/request",
    "latency_scope": "complete target-free offline inference with prebuilt context and fitted snapshot; no data load, fitting, network or API",
    "cold_latency_scope": "repeated identical empty context; cohort quality counted in full",
    "numeric_threads": 1,
    "blind_holdout": False,
}


def digest(value: object) -> str:
    return diversity.digest(value)


def code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    value = hashlib.sha256()
    for relative in (
        "scripts/benchmark_model_policy.py",
        "src/ecommerce_recsys/evaluation/model_policy.py",
    ):
        value.update(relative.encode("utf-8"))
        value.update((root / relative).read_bytes().replace(b"\r\n", b"\n"))
    value.update(diversity.code_fingerprint().encode("ascii"))
    return value.hexdigest()


def result_fingerprint(artifact: dict) -> str:
    """Identify scores/models independently of measured timings and runtime costs."""
    rows = [
        {
            key: row[key]
            for key in ("fold_index", "cutoff", "ranker_training_folds", "model", "warm", "cold")
        }
        for row in artifact.get("folds", [])
    ]
    return digest({"folds": rows, "selected_routes": artifact.get("selected_routes")})


def write_artifact(path: Path, artifact: dict) -> None:
    artifact["result_sha256"] = result_fingerprint(artifact)
    artifact["payload_sha256"] = digest(
        {key: value for key, value in artifact.items() if key != "payload_sha256"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_bytes((json.dumps(artifact, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    pending.replace(path)


def read_artifact(path: Path, expected: dict) -> dict:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise ValueError("Model-policy artifact provenance or policy differs from this run.")
    if artifact.get("payload_sha256") != digest(
        {key: value for key, value in artifact.items() if key != "payload_sha256"}
    ) or artifact.get("result_sha256") != result_fingerprint(artifact):
        raise ValueError("Model-policy artifact payload or result checksum differs.")
    return artifact


def upstream_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        input_path=args.input_path,
        fold_dir=args.fold_dir,
        manifest=args.manifest,
        sweep_dir=args.sweep_dir,
        reference=args.reference,
        m10_data_dir=args.ranking_data_dir,
        m10_quality=args.ranking_quality,
        ranker_development=args.ranker_development,
        ranker_lock=args.ranker_lock,
        ranker_diagnostic=args.ranker_diagnostic,
        development_artifact=args.diversity_development,
        selection_lock=args.diversity_lock,
        diagnostic_artifact=args.diversity_diagnostic,
    )


def published_artifact_hashes(args: argparse.Namespace) -> dict[str, str]:
    """Pin existing model/diagnostic files without using their scores for selection."""
    return {
        "published_ranker_diagnostic_sha256": sha256_file(args.ranker_diagnostic),
        "published_diversity_diagnostic_sha256": sha256_file(args.diversity_diagnostic),
    }


def inputs(args: argparse.Namespace, max_fold: int):
    upstream = upstream_args(args)
    manifest, configs, diversity_identity, _, ranker_identity, quality = diversity.inputs(
        upstream, max_fold=max_fold
    )
    validate_boundaries(manifest)
    diversity_development, diversity_lock = diversity.require_development_and_lock(
        upstream, diversity_identity, manifest
    )
    if diversity_lock["selected_bonus"] != POLICY["category_bonus"]:
        raise ValueError("Model-policy grid requires the published category bonus.")
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    if reference.get("payload_sha256") != candidate_payload_fingerprint(reference):
        raise ValueError("Candidate reference payload changed.")
    reference_rows = {}
    for row in reference["results"]:
        key = (row["fold_index"], row["cohort"], row["generator"])
        if key in reference_rows:
            raise ValueError("Candidate reference has duplicate comparisons.")
        reference_rows[key] = row
    required_names = {*[spec.generator for spec in WARM_POLICIES], "hybrid"}
    if any(
        (index, cohort, name) not in reference_rows
        for index in range(1, 10)
        for cohort in ("warm", "cold")
        for name in required_names
    ):
        raise ValueError("Model-policy comparison requires the complete candidate reference.")
    identity = {
        "protocol_version": "rolling-temporal",
        "upstream_identity": diversity_identity,
        "diversity_development_sha256": sha256_file(args.diversity_development),
        "diversity_lock_sha256": sha256_file(args.diversity_lock),
        **published_artifact_hashes(args),
        "policy": POLICY,
        "code_sha256": code_fingerprint(),
        "runtime": {
            **ranker_identity["runtime"],
            "implicit": implicit.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
    }
    ranker_development = ranker.read_validated_artifact(
        args.ranker_development,
        {"benchmark": "pairwise-ranker-development-v1", **ranker_identity},
    )
    return (
        manifest,
        configs,
        identity,
        reference_rows,
        quality,
        ranker_identity,
        ranker_development,
        diversity_development,
    )


def validate_boundaries(manifest: dict) -> None:
    previous_end = None
    for fold in manifest["folds"]:
        for name in (
            "fold_index",
            "train_cutoff",
            "evaluation_cutoff",
            "training_interactions",
            "train_catalog_items",
            "warm_target_users",
            "cold_target_users",
        ):
            if type(fold[name]) is not int or fold[name] < 0:
                raise ValueError("Fold boundaries and counts must be nonnegative plain integers.")
        if fold["train_cutoff"] >= fold["evaluation_cutoff"] or (
            previous_end is not None and previous_end > fold["train_cutoff"]
        ):
            raise ValueError("Fold time boundaries overlap or have an empty future window.")
        previous_end = fold["evaluation_cutoff"]


def model_record(model: PairwiseRanker) -> dict:
    return {
        "weights": model.weights.tolist(),
        "scales": model.scales.tolist(),
        "alpha": model.alpha,
        "iterations": model.iterations,
        "converged": model.converged,
    }


class OfflinePredictor:
    """Run a complete policy without accepting future targets or labels."""

    def __init__(self, *, sources, hybrids, features, model, fold_index, categories):
        self.sources = {source.name: source for source in sources}
        self.generators = {
            **self.sources,
            **{hybrid.name: hybrid for hybrid in hybrids},
            "popularity_rrf": HybridCandidateGenerator(
                [self.sources[name] for name in ("recent_popularity", "global_popularity")],
                name="popularity_rrf",
            ),
        }
        self.features = features
        self.model = model
        self.fold_index = fold_index
        self.categories = categories
        self.catalog = frozenset(categories)

    def validate_pool(self, pool: list[Candidate], context: RetrievalContext) -> None:
        ids = [candidate.item_id for candidate in pool]
        if (
            len(ids) > CANDIDATE_BUDGET
            or len(set(ids)) != len(ids)
            or not set(ids).issubset(self.catalog)
            or set(ids).intersection(context.history)
        ):
            raise ValueError(
                "Offline policy returned duplicate, seen or out-of-catalog candidates."
            )

    def feature_rows(
        self, pool: list[Candidate], context: RetrievalContext, cache=None
    ) -> list[dict]:
        if context.user_id is None or not context.history:
            raise ValueError("Learned policy requires a warm user and training history.")
        self.validate_pool(pool, context)
        seen = frozenset(context.history)
        key = request_id(self.fold_index, context.user_id)
        rows = []
        for rank, candidate in enumerate(pool, start=1):
            cached = cache.get(candidate.item_id) if cache is not None else None
            if cached is None:
                row = self.features.candidate_row(
                    fold_index=self.fold_index,
                    context=context,
                    candidate=candidate,
                    rank=rank,
                    target_item_id="",  # Target labels are excluded from inference predictors.
                    request_key=key,
                    seen_items=seen,
                )
            else:
                if cached.get("request_id") != key or cached.get("fold_index") != self.fold_index:
                    raise ValueError("Cached ranking features belong to a different request.")
                row = cached.copy()
                evidence = {entry.source: entry for entry in candidate.evidence}
                if not evidence or not set(evidence).issubset(SOURCE_NAMES):
                    raise ValueError("Candidate has unexpected source evidence.")
                row.update(
                    retrieval_rank=rank, rrf_score=candidate.score, source_count=len(evidence)
                )
                for source in SOURCE_NAMES:
                    entry = evidence.get(source)
                    row[f"{source}_present"] = int(entry is not None)
                    row[f"{source}_rank"] = entry.rank if entry is not None else ABSENT_SOURCE_RANK
                    row[f"{source}_score"] = entry.score if entry is not None else 0.0
            rows.append(row)
        return rows

    def scores(self, pool: list[Candidate], context: RetrievalContext) -> np.ndarray:
        rows = self.feature_rows(pool, context)
        return self.model.score(feature_matrix(pd.DataFrame(rows))) if rows else np.empty(0)

    def order(self, spec: PolicySpec, pool: list[Candidate], scores=None) -> list[str]:
        ids = [candidate.item_id for candidate in pool]
        if not spec.learned:
            return ids[: K_VALUES[-1]]
        order = category_novelty_order(
            ids,
            scores,
            [self.categories[item] for item in ids],
            bonus=spec.bonus,
            shortlist_size=POLICY["category_shortlist"],
            limit=K_VALUES[-1],
        )
        return [ids[index] for index in order]

    def predict(self, spec: PolicySpec, context: RetrievalContext) -> tuple[list[str], list[str]]:
        pool = self.generators[spec.generator].generate(context, CANDIDATE_BUDGET)
        self.validate_pool(pool, context)
        output = self.order(spec, pool, self.scores(pool, context) if spec.learned else None)
        if len(set(output)) != len(output) or not set(output).issubset(
            candidate.item_id for candidate in pool
        ):
            raise ValueError("Offline policy output violates its candidate pool.")
        return [candidate.item_id for candidate in pool], output

    def quality_outputs(self, context: RetrievalContext) -> dict[str, tuple[list[str], list[str]]]:
        pools = {
            name: source.generate(context, CANDIDATE_BUDGET)
            for name, source in self.sources.items()
        }
        for name in ("hybrid", "hybrid_without_als"):
            generator = self.generators[name]
            pools[name] = generator.fuse(
                {source.name: pools[source.name] for source in generator.sources},
                context,
                CANDIDATE_BUDGET,
            )
        for pool in pools.values():
            self.validate_pool(pool, context)
        full_rows = self.feature_rows(pools["hybrid"], context)
        cached = {row["item_id"]: row for row in full_rows}
        no_als_rows = self.feature_rows(pools["hybrid_without_als"], context, cached)
        learned = {
            name: self.model.score(feature_matrix(pd.DataFrame(rows))) if rows else np.empty(0)
            for name, rows in (("hybrid", full_rows), ("hybrid_without_als", no_als_rows))
        }
        return {
            spec.name: (
                [candidate.item_id for candidate in pools[spec.generator]],
                self.order(spec, pools[spec.generator], learned.get(spec.generator)),
            )
            for spec in WARM_POLICIES
        }


def latency_sample(
    contexts: dict[str, RetrievalContext], fold_index: int
) -> list[RetrievalContext]:
    return [
        contexts[user]
        for user in sorted(contexts, key=lambda user: request_id(fold_index, user))[
            : POLICY["warm_latency_requests"]
        ]
    ]


def measure_latency(predictor, contexts, specs, *, repetitions: int, expected: dict) -> dict:
    durations = {spec.name: [] for spec in specs}
    if contexts:
        for spec in specs:
            predictor.predict(spec, contexts[0])  # One excluded warmup per fixed policy.
    for repeat in range(repetitions):
        for position, context in enumerate(contexts):
            offset = (repeat + position) % len(specs)
            for spec in (*specs[offset:], *specs[:offset]):
                started = perf_counter()
                pool, output = predictor.predict(spec, context)
                durations[spec.name].append(perf_counter() - started)
                if digest([pool, output]) != expected[context.user_id][spec.name]:
                    raise ValueError(
                        "Independent policy call differs from shared quality evaluation."
                    )
    return {name: latency_metrics(values) for name, values in durations.items()}


def check_parity(result: dict, reference: dict, *, order: dict | None = None) -> None:
    totals = reference["totals"][str(CANDIDATE_BUDGET)]
    if (
        result["requests"] != reference["evaluation_users"]
        or result["reachable_targets"] != reference["reachable_targets"]
        or result["target_in_pool"] != totals["hits"]
        or result["candidate_count"] != totals["candidate_count"]
        or result["empty_pools"] != totals["empty_requests"]
        or result["full_pools"] != totals["full_requests"]
    ):
        raise ValueError(
            "Model-policy candidate counts differ from the frozen retrieval reference."
        )
    if order is not None:
        for k in K_VALUES:
            if result["hits"][str(k)] != order["hits"][str(k)] or any(
                not math.isclose(
                    result[f"{metric}@{k}"], order[f"{metric}@{k}"], rel_tol=0, abs_tol=1e-12
                )
                for metric in ("HR", "MRR", "NDCG")
            ):
                raise ValueError("Model-policy ordering differs from the frozen learned reference.")


def evaluate_fold(
    args,
    *,
    fold,
    interactions,
    configs,
    model,
    training_folds,
    ranker_metrics,
    diversity_metrics,
    reference_rows,
    training_cost,
) -> dict:
    index = fold["fold_index"]
    cutoff = int(fold["train_cutoff"])
    train = interactions.loc[interactions["timestamp"] <= cutoff]
    folder = args.fold_dir / f"fold_{index:02d}"
    catalog = pd.read_parquet(folder / "items_train.parquet")
    targets = {
        cohort: pd.read_parquet(folder / f"{cohort}_targets.parquet") for cohort in ("warm", "cold")
    }
    categories = diversity.category_map(catalog, expected_items=fold["train_catalog_items"])
    if len(train) != fold["training_interactions"] or set(train["item_id"].astype(str)) != set(
        categories
    ):
        raise ValueError("Model-policy training/catalog snapshot differs from the manifest.")
    for cohort, frame in targets.items():
        if (
            len(frame) != fold[f"{cohort}_target_users"]
            or not (
                (frame["timestamp"] > cutoff) & (frame["timestamp"] <= fold["evaluation_cutoff"])
            ).all()
        ):
            raise ValueError(
                "Model-policy target count or time boundary differs from the manifest."
            )
        validate_targets(train, frame, cohort)
    started = perf_counter()
    features = SnapshotFeatures.from_frames(train, catalog, cutoff)
    snapshot_seconds = perf_counter() - started
    sources, hybrids, fit_seconds, factor_bytes = ranker.build_sources(
        train, catalog, cutoff, configs
    )
    predictor = OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=features,
        model=model,
        fold_index=index,
        categories=categories,
    )
    user_ids = set(targets["warm"]["user_id"].astype(str))
    rows = train.loc[train["user_id"].astype(str).isin(user_ids)].copy()
    rows["user_id"] = rows["user_id"].astype(str)
    contexts = {
        user: RetrievalContext(user, tuple(frame["item_id"].astype(str)))
        for user, frame in rows.groupby("user_id", sort=False)
    }
    if set(contexts) != user_ids:
        raise ValueError("Warm policy contexts differ from the declared target users.")
    sample = latency_sample(contexts, index)
    sampled_users = {context.user_id for context in sample}
    expected = {}
    warm_totals = {spec.name: PolicyTotals(predictor.catalog, categories) for spec in WARM_POLICIES}
    started = perf_counter()
    for position, target in enumerate(targets["warm"].itertuples(index=False), start=1):
        user = str(target.user_id)
        context = contexts[user]
        outputs = predictor.quality_outputs(context)
        for name, (pool, output) in outputs.items():
            warm_totals[name].add(pool, output, str(target.item_id), frozenset(context.history))
        if user in sampled_users:
            expected[user] = {name: digest(value) for name, value in outputs.items()}
        if position % 500 == 0 or position == len(targets["warm"]):
            print(
                f"  policy fold {index}: {position:,}/{len(targets['warm']):,} warm requests",
                flush=True,
            )
    warm_quality_seconds = perf_counter() - started
    warm = {name: total.output() for name, total in warm_totals.items()}
    for spec in WARM_POLICIES:
        order = None
        if spec.name == "hybrid_learned":
            order = ranker_metrics["learned"]
        elif spec.name == "hybrid_category":
            order = diversity_metrics
        elif spec.name == "hybrid_rrf":
            order = ranker_metrics["rrf"]
        check_parity(warm[spec.name], reference_rows[(index, "warm", spec.generator)], order=order)
    for name, reference_name in (("hybrid_learned", "0.0"), ("hybrid_category", "0.1")):
        original = diversity_metrics if reference_name == "0.1" else None
        if original is not None and any(
            warm[name][key] != original[key]
            for key in (
                "known_category_item_slots",
                "distinct_known_category_slots",
                "unique_items",
                "recommendation_slots",
            )
        ):
            raise ValueError(
                "Model-policy category totals differ from the frozen re-ranking reference."
            )
    cold_context = RetrievalContext()
    cold_expected = {None: {}}
    cold = {}
    target_counts = Counter(targets["cold"]["item_id"].astype(str))
    for spec in COLD_POLICIES:
        pool, output = predictor.predict(spec, cold_context)
        totals = PolicyTotals(predictor.catalog, categories)
        totals.add_shared(pool, output, target_counts)
        cold[spec.name] = totals.output()
        cold_expected[None][spec.name] = digest([pool, output])
        generator = "hybrid" if spec.name == "popularity_rrf" else spec.generator
        check_parity(cold[spec.name], reference_rows[(index, "cold", generator)])
    print(f"  policy fold {index}: paired offline latency sample", flush=True)
    warm_latency = measure_latency(
        predictor,
        sample,
        WARM_POLICIES,
        repetitions=POLICY["warm_latency_repetitions"],
        expected=expected,
    )
    cold_latency = measure_latency(
        predictor,
        [cold_context],
        COLD_POLICIES,
        repetitions=POLICY["cold_latency_repetitions"],
        expected=cold_expected,
    )
    row = {
        "fold_index": index,
        "cutoff": cutoff,
        "ranker_training_folds": training_folds,
        "model": model_record(model),
        "warm": warm,
        "cold": cold,
        "costs": {
            "source_fit_seconds": fit_seconds,
            "snapshot_feature_seconds": snapshot_seconds,
            "ranker_training": training_cost,
            "als_factor_array_bytes": factor_bytes,
            "warm_shared_quality_seconds": warm_quality_seconds,
            "source_fit_estimate_by_policy_seconds": {
                spec.name: sum(fit_seconds[name] for name in spec.sources) for spec in WARM_POLICIES
            },
        },
        "latency": {
            "warm": warm_latency,
            "cold": cold_latency,
            "warm_sample_sha256": digest(
                [request_id(index, context.user_id) for context in sample]
            ),
        },
    }
    validate_fold(row, fold)
    return row


def validate_fold(row: dict, fold: dict) -> None:
    index = fold["fold_index"]
    training_folds = list(range(1, min(index, 5)))
    if (
        row["fold_index"] != index
        or row["cutoff"] != fold["train_cutoff"]
        or row["ranker_training_folds"] != training_folds
    ):
        raise ValueError("Policy fold identity or ranker training chronology differs.")
    record = row["model"]
    weights = np.asarray(record["weights"], dtype=float)
    scales = np.asarray(record["scales"], dtype=float)
    if (
        weights.shape != (len(ranker.FEATURE_NAMES),)
        or scales.shape != weights.shape
        or not np.isfinite(weights).all()
        or not np.isfinite(scales).all()
        or not (scales > 0).all()
        or record["alpha"] != POLICY["ranker_alpha"]
        or record["converged"] is not True
    ):
        raise ValueError("Policy fold has invalid or unconverged ranker parameters.")
    costs = row["costs"]
    for values in (
        costs["source_fit_seconds"],
        costs["source_fit_estimate_by_policy_seconds"],
        {name: costs[name] for name in ("snapshot_feature_seconds", "warm_shared_quality_seconds")},
        {name: costs["ranker_training"][name] for name in ("pair_sampling_seconds", "fit_seconds")},
    ):
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in values.values()
        ):
            raise ValueError("Policy fit/training cost must be finite and nonnegative.")
    if type(costs["als_factor_array_bytes"]) is not int or costs["als_factor_array_bytes"] < 0:
        raise ValueError("ALS factor storage must be a nonnegative integer byte count.")
    if set(costs["source_fit_seconds"]) != {
        name for spec in WARM_POLICIES for name in spec.sources
    }:
        raise ValueError("Policy fit record has missing or extra sources.")
    estimates = {
        spec.name: sum(costs["source_fit_seconds"][name] for name in spec.sources)
        for spec in WARM_POLICIES
    }
    if costs["source_fit_estimate_by_policy_seconds"] != estimates:
        raise ValueError("Policy attributed source-fit costs do not reconcile.")
    for cohort, specs in (("warm", WARM_POLICIES), ("cold", COLD_POLICIES)):
        if set(row[cohort]) != {spec.name for spec in specs} or set(row["latency"][cohort]) != set(
            row[cohort]
        ):
            raise ValueError("Policy fold has an incomplete or extra comparison.")
        for spec in specs:
            validate_result(
                row[cohort][spec.name],
                requests=fold[f"{cohort}_target_users"],
                catalog_size=fold["train_catalog_items"],
            )
            timing = row["latency"][cohort][spec.name]
            expected_samples = (
                min(POLICY["warm_latency_requests"], fold["warm_target_users"])
                * POLICY["warm_latency_repetitions"]
                if cohort == "warm"
                else POLICY["cold_latency_repetitions"]
            )
            if (
                type(timing["latency_samples"]) is not int
                or timing["latency_samples"] != expected_samples
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                    for value in timing.values()
                )
            ):
                raise ValueError("Policy fold latency samples are invalid or incomplete.")
            if not timing["latency_p50_ms"] <= timing["latency_p95_ms"] <= timing["latency_p99_ms"]:
                raise ValueError("Policy fold latency quantiles are out of order.")


def validate_completion(artifact: dict, manifest: dict, phase: str) -> None:
    expected = POLICY[f"{phase}_folds"]
    rows = artifact.get("folds", [])
    if [row["fold_index"] for row in rows] != expected[: len(rows)] or len(rows) > len(expected):
        raise ValueError("Model-policy checkpoint has noncontiguous or invalid phase folds.")
    if type(artifact.get("complete")) is not bool or artifact["complete"] != (
        len(rows) == len(expected)
    ):
        raise ValueError("Model-policy checkpoint completion flag differs from fold coverage.")
    for row in rows:
        validate_fold(row, manifest["folds"][row["fold_index"] - 1])
        if phase == "diagnostic" and digest(row["model"]) != artifact["ranker_model_sha256"]:
            raise ValueError("Diagnostic policy model differs from its frozen upstream model.")
    if (
        phase == "development"
        and artifact["complete"]
        and artifact.get("selected_routes") != select_routes(rows)
    ):
        raise ValueError("Saved route selection differs from the fixed development rule.")
    if artifact["complete"]:
        pooled = {
            cohort: {spec.name: pooled_results(rows, cohort, spec.name) for spec in specs}
            for cohort, specs in (("warm", WARM_POLICIES), ("cold", COLD_POLICIES))
        }
        if artifact.get("pooled") != pooled:
            raise ValueError("Saved pooled results differ from the fold numerators.")
    elif "pooled" in artifact or (phase == "development" and "selected_routes" in artifact):
        raise ValueError("Partial policy checkpoint must not present final pooling or a selection.")


def require_lock(args, identity, manifest) -> dict:
    development = read_artifact(
        args.development_artifact, {"benchmark": "model-policy-development-v1", **identity}
    )
    validate_completion(development, manifest, "development")
    if not development["complete"]:
        raise ValueError("Model-policy lock requires all development folds 2–4.")
    selected = select_routes(development["folds"])
    expected = {
        "benchmark": "model-policy-selection-lock-v1",
        **identity,
        "development_artifact_sha256": sha256_file(args.development_artifact),
        "development_result_sha256": development["result_sha256"],
        "selected_routes": selected,
        "route_specs": {
            cohort: next(spec.record() for spec in specs if spec.name == selected[cohort])
            for cohort, specs in (("warm", WARM_POLICIES), ("cold", COLD_POLICIES))
        },
    }
    if args.phase == "lock" and not args.selection_lock.exists():
        write_artifact(
            args.selection_lock,
            {**expected, "role": "offline reference; later periods are post-selection diagnostics"},
        )
    if not args.selection_lock.exists():
        raise ValueError("Model-policy diagnostic requires an explicitly created development lock.")
    return read_artifact(args.selection_lock, expected)


def run(args: argparse.Namespace) -> None:
    if args.phase not in {"development", "lock", "diagnostic"}:
        raise ValueError("Unknown model-policy phase.")
    if type(args.max_fold) is not int or not 5 <= args.max_fold <= 9:
        raise ValueError("Diagnostic max fold must be an integer in 5–9.")
    max_fold = args.max_fold if args.phase == "diagnostic" else 4
    (
        manifest,
        configs,
        identity,
        reference_rows,
        quality,
        ranker_identity,
        ranker_dev,
        diversity_dev,
    ) = inputs(args, max_fold)
    for index in POLICY[f"{'diagnostic' if args.phase == 'diagnostic' else 'development'}_folds"]:
        for prior in range(1, min(index, 5)):
            if (
                manifest["folds"][prior - 1]["evaluation_cutoff"]
                > manifest["folds"][index - 1]["train_cutoff"]
            ):
                raise ValueError("Ranker training labels occur after the scoring fold cutoff.")
    if args.phase == "lock":
        lock = require_lock(args, identity, manifest)
        print(f"Locked offline routes: {lock['selected_routes']}", flush=True)
        return
    phase = args.phase
    expected = {"benchmark": f"model-policy-{phase}-v1", **identity}
    model = ranker_diag = diversity_diag = None
    if phase == "diagnostic":
        lock = require_lock(args, identity, manifest)
        model, ranker_diag = diversity.locked_ranker_model(upstream_args(args), ranker_identity)
        diversity_diag = diversity.read_artifact(
            args.diversity_diagnostic,
            {
                "benchmark": "diversity-diagnostic-v1",
                **identity["upstream_identity"],
                "selection_lock_sha256": sha256_file(args.diversity_lock),
                "ranker_diagnostic_sha256": sha256_file(args.ranker_diagnostic),
                "selected_bonus": POLICY["category_bonus"],
            },
        )
        diversity._validate_rows(
            diversity_diag["folds"], manifest, phase="diagnostic", names={"0.0", "0.1"}
        )
        diversity._validate_completion(diversity_diag, phase="diagnostic")
        if not diversity_diag["complete"]:
            raise ValueError(
                "Model-policy diagnostics require complete upstream re-ranking diagnostics."
            )
        expected.update(
            {
                "selection_lock_sha256": sha256_file(args.selection_lock),
                "selected_routes": lock["selected_routes"],
                "ranker_diagnostic_sha256": sha256_file(args.ranker_diagnostic),
                "diversity_diagnostic_sha256": sha256_file(args.diversity_diagnostic),
                "ranker_model_sha256": digest(model_record(model)),
            }
        )
    path = args.development_artifact if phase == "development" else args.diagnostic_artifact
    artifact = (
        read_artifact(path, expected)
        if path.exists()
        else {
            **expected,
            "role": "reused development selection"
            if phase == "development"
            else "post-selection diagnostic; not blind validation",
            "folds": [],
            "complete": False,
        }
    )
    validate_completion(artifact, manifest, phase)
    pending = [
        index
        for index in POLICY[f"{phase}_folds"]
        if index <= max_fold and index not in {row["fold_index"] for row in artifact["folds"]}
    ]
    if not pending:
        print(f"Verified {phase} checkpoint; no folds pending.", flush=True)
        return
    interactions = pd.read_parquet(args.input_path)
    for index in pending:
        training_folds = list(range(1, min(index, 5)))
        training_cost = {
            "role": "reused frozen folds 1–4 model",
            "pair_sampling_seconds": 0.0,
            "fit_seconds": 0.0,
        }
        if phase == "development":
            started = perf_counter()
            pairs, counts = ranker.training_samples(
                diversity.upstream_args(upstream_args(args)), quality, training_folds
            )
            sampling_seconds = perf_counter() - started
            started = perf_counter()
            model = PairwiseRanker.fit(
                pairs, alpha=POLICY["ranker_alpha"], max_iterations=ranker.POLICY["max_iterations"]
            )
            training_cost = {
                "role": "earlier labelled folds",
                "pair_sampling_seconds": sampling_seconds,
                "fit_seconds": perf_counter() - started,
                "counts": counts,
            }
            del pairs
            ranker_metrics = ranker_dev["folds"][index - 2]["configs"]["0.01"]["metrics"]
            diversity_metrics = diversity_dev["folds"][index - 2]["configs"]["0.1"]
        else:
            ranker_metrics = ranker_diag["folds"][index - 5]["metrics"]
            diversity_metrics = diversity_diag["folds"][index - 5]["configs"]["0.1"]
        row = evaluate_fold(
            args,
            fold=manifest["folds"][index - 1],
            interactions=interactions,
            configs=configs,
            model=model,
            training_folds=training_folds,
            ranker_metrics=ranker_metrics,
            diversity_metrics=diversity_metrics,
            reference_rows=reference_rows,
            training_cost=training_cost,
        )
        artifact["folds"].append(row)
        artifact["complete"] = len(artifact["folds"]) == len(POLICY[f"{phase}_folds"])
        if phase == "development" and artifact["complete"]:
            artifact["selected_routes"] = select_routes(artifact["folds"])
        if artifact["complete"]:
            artifact["pooled"] = {
                cohort: {
                    spec.name: pooled_results(artifact["folds"], cohort, spec.name)
                    for spec in specs
                }
                for cohort, specs in (("warm", WARM_POLICIES), ("cold", COLD_POLICIES))
            }
        validate_completion(artifact, manifest, phase)
        write_artifact(path, artifact)
        print(
            f"Saved model-policy {phase} fold {index}; complete={artifact['complete']}", flush=True
        )


@single_thread_benchmark
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("development", "lock", "diagnostic"))
    for name, default in (
        ("input-path", "data/processed/interactions.parquet"),
        ("fold-dir", "data/rolling"),
        ("manifest", "benchmarks/rolling/manifest.json"),
        ("sweep-dir", "benchmarks/rolling"),
        ("reference", "benchmarks/retrieval/candidates.json"),
        ("ranking-data-dir", "data/ranking/m10_v1"),
        ("ranking-quality", "benchmarks/ranking/m10_quality_v1.json"),
        ("ranker-development", "benchmarks/ranking/ranker_development_v1.json"),
        ("ranker-lock", "benchmarks/ranking/ranker_selection_lock_v1.json"),
        ("ranker-diagnostic", "benchmarks/ranking/ranker_diagnostic_v1.json"),
        ("diversity-development", "benchmarks/ranking/diversity_development_v1.json"),
        ("diversity-lock", "benchmarks/ranking/diversity_selection_lock_v1.json"),
        ("diversity-diagnostic", "benchmarks/ranking/diversity_diagnostic_v1.json"),
        ("development-artifact", "benchmarks/model_policy/development_v1.json"),
        ("selection-lock", "benchmarks/model_policy/selection_lock_v1.json"),
        ("diagnostic-artifact", "benchmarks/model_policy/diagnostic_v1.json"),
    ):
        parser.add_argument(f"--{name}", type=Path, default=Path(default))
    parser.add_argument("--max-fold", type=int, default=9)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
