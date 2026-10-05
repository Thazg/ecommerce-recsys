from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ecommerce_recsys.evaluation.benchmark import evaluate_recommender
from ecommerce_recsys.recommendation.matrix_factorization import (
    MatrixFactorizationRecommender,
)

DATA_DIR = Path("data/processed")
BENCHMARK_DIR = Path("benchmarks/mf")
OUTPUT_PATH = BENCHMARK_DIR / "als_experiments_v1.json"

K_VALUES = (5, 10, 20)

BASELINE_FACTORS = 64
BASELINE_ITERATIONS = 20
BASELINE_REGULARIZATION = 0.01

FACTOR_VALUES = (32, 64, 128)
REGULARIZATION_VALUES = (0.001, 0.01, 0.1)
ITERATION_VALUES = (10, 20, 40)

RANDOM_SEED = 42
CANDIDATE_FACTORS = 128
CANDIDATE_ITERATIONS = 40
CANDIDATE_REGULARIZATION = 0.01


def run_experiment(
    experiment_id: str,
    axis: str,
    factors: int,
    iterations: int,
    regularization: float,
    train: pd.DataFrame,
    validation: pd.DataFrame,
    catalog_size: int,
) -> dict:
    print(f"\n{'=' * 60}")
    print(f"Experiment: {experiment_id}")
    print(f"Axis: {axis}")
    print(f"factors={factors}")
    print(f"iterations={iterations}")
    print(f"regularization={regularization}")
    print(f"{'=' * 60}")

    recommender = MatrixFactorizationRecommender(
        factors=factors,
        iterations=iterations,
        regularization=regularization,
        random_state=RANDOM_SEED,
    )

    print("Fitting ALS on train split...")
    recommender.fit(train)

    print("Evaluating on validation split...")

    metrics = evaluate_recommender(
        recommender=recommender,
        train=train,
        test=validation,
        k_values=K_VALUES,
        total_catalog_items=catalog_size,
        fit=False,
        split_protocol="legacy_leave_last_out",
    )

    return {
        "experiment_id": experiment_id,
        "axis": axis,
        "factors": factors,
        "iterations": iterations,
        "regularization": regularization,
        "random_seed": RANDOM_SEED,
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run controlled ALS validation experiments.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run only the baseline ALS configuration.",
    )
    parser.add_argument(
        "--experiment",
        choices=("factors", "regularization", "iterations", "candidate_128_40", "all"),
        default="all",
        help="Select which ALS experiment axis or candidate configuration   to run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    train_path = DATA_DIR / "train.parquet"
    validation_path = DATA_DIR / "val.parquet"
    items_path = DATA_DIR / "items.parquet"

    print("Loading evaluation data...")

    train = pd.read_parquet(train_path)
    validation = pd.read_parquet(validation_path)
    items = pd.read_parquet(items_path)

    catalog_size = items["item_id"].nunique()

    print(f"Train: {train.shape}")
    print(f"Validation: {validation.shape}")
    print(f"Catalog: {catalog_size}")

    experiments: list[dict] = []

    if args.smoke_test:
        experiments.append(
            run_experiment(
                experiment_id="baseline_smoke",
                axis="baseline",
                factors=BASELINE_FACTORS,
                iterations=BASELINE_ITERATIONS,
                regularization=BASELINE_REGULARIZATION,
                train=train,
                validation=validation,
                catalog_size=catalog_size,
            )
        )

    if args.experiment in ("factors", "all") and not args.smoke_test:
        for factors in FACTOR_VALUES:
            experiments.append(
                run_experiment(
                    experiment_id=f"factors_{factors}",
                    axis="factors",
                    factors=factors,
                    iterations=BASELINE_ITERATIONS,
                    regularization=BASELINE_REGULARIZATION,
                    train=train,
                    validation=validation,
                    catalog_size=catalog_size,
                )
            )

    if args.experiment in ("regularization", "all") and not args.smoke_test:
        for regularization in REGULARIZATION_VALUES:
            experiments.append(
                run_experiment(
                    experiment_id=f"regularization_{regularization}",
                    axis="regularization",
                    factors=BASELINE_FACTORS,
                    iterations=BASELINE_ITERATIONS,
                    regularization=regularization,
                    train=train,
                    validation=validation,
                    catalog_size=catalog_size,
                )
            )

    if args.experiment in ("iterations", "all") and not args.smoke_test:
        for iterations in ITERATION_VALUES:
            experiments.append(
                run_experiment(
                    experiment_id=f"iterations_{iterations}",
                    axis="iterations",
                    factors=BASELINE_FACTORS,
                    iterations=iterations,
                    regularization=BASELINE_REGULARIZATION,
                    train=train,
                    validation=validation,
                    catalog_size=catalog_size,
                )
            )

    if args.experiment == "candidate_128_40" and not args.smoke_test:
        experiments.append(
            run_experiment(
                experiment_id="candidate_128_40",
                axis="candidate",
                factors=CANDIDATE_FACTORS,
                iterations=CANDIDATE_ITERATIONS,
                regularization=CANDIDATE_REGULARIZATION,
                train=train,
                validation=validation,
                catalog_size=catalog_size,
            )
        )

    artifact = {
        "experiment_version": "v1",
        "model": "implicit_als",
        "evaluation_protocol": {
            "training_split": "train.parquet",
            "evaluation_split": "val.parquet",
            "k_values": list(K_VALUES),
            "catalog_size": catalog_size,
            "training_interactions": len(train),
            "evaluation_users": len(validation),
            "random_seed": RANDOM_SEED,
            "latency_measurement": ("per-user recommendation latency; fit/training time excluded"),
        },
        "baseline_config": {
            "factors": BASELINE_FACTORS,
            "iterations": BASELINE_ITERATIONS,
            "regularization": BASELINE_REGULARIZATION,
        },
        "experiments": experiments,
    }

    BENCHMARK_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(
            artifact,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nExperiment artifact written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
