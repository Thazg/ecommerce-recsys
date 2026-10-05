# E-commerce recommendation system

An offline recommendation project built on the Retailrocket interaction dataset. The repository contains data preparation, temporal evaluation, popularity baselines, ItemKNN, educational MF/BPR, and implicit ALS. Candidate generation and online serving are planned but not implemented.

## Evaluation

The current benchmark uses nine chronological folds. Every model in a fold trains on the same earlier interactions and recommends from the same training-time catalog. The primary task predicts each returning user's first previously unseen item in the next window; first-time users are evaluated separately. The benchmark contains **90,107 warm user-window targets from 71,982 distinct users** and **1,262,289 first-time user targets**.

| Model | HR@20 on folds 5–9 |
| :--- | ---: |
| Random | 0.000034 |
| Global Popularity | 0.007855 |
| Recent Popularity | 0.008209 |
| Category Popularity | 0.041518 |
| ItemKNN (selected shrinkage) | 0.041889 |
| Implicit ALS (selected configuration) | 0.027291 |

ItemKNN and ALS configurations were selected using folds 1–4. The five-fold figures above are **exploratory post-selection results**, because reference scores for folds 5–9 had already been inspected before the sweep configurations were locked. The ItemKNN–Category Popularity difference is too small to establish a reliable winner. See the [benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) for MRR, NDCG, coverage, latency, cold-user results, and limitations.

## Repository guide

- [Rolling evaluation protocol](docs/ROLLING_EVALUATION_PROTOCOL.md): cohorts, time boundaries, selection rule, and validity limits.
- [Benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) and [result artifacts](benchmarks/rolling/): measured outcomes and per-fold data.
- [Current architecture](docs/ARCHITECTURE_CURRENT.md) and [project status](docs/PROJECT_STATUS.md): implemented components and next steps.
- [Dataset card](docs/DATASET_CARD.md) and [data contract](docs/DATA_CONTRACT.md): source, schema, and processing assumptions.
- [Engineering decisions](docs/DECISIONS.md): design rationale, including the transition from per-user leave-last-out to global temporal folds.

Earlier leave-last-out experiments remain in the [baseline](docs/BASELINE_REPORT.md) and [MF](docs/MF_EXPERIMENT_REPORT.md) reports as historical evidence. Their scores answer a different evaluation question and should not be compared directly with the rolling results.

## Reproduce

Use Python 3.13 from the repository root. Place the Retailrocket CSVs in `data/raw/` as described in the [data instructions](data/raw/README.md), then run:

```sh
python -m pip install -e ".[dev]"
python scripts/build_interactions.py
python scripts/prepare_rolling_data.py
python scripts/sweep_rolling.py --model item_knn
python scripts/sweep_rolling.py --model als
python scripts/benchmark_rolling.py
python scripts/benchmark_rolling_cold.py
pytest
ruff check .
ruff format --check .
```

The raw CSVs and generated Parquet files are not committed. If they reside elsewhere, pass `--input-path` and `--raw-dir` to the preparation command, and `--input-path` to the sweep and benchmark commands. The manifest records SHA-256 hashes for the processed interactions, raw item properties, and each generated fold file; runners verify those hashes before resuming.
