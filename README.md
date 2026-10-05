# E-commerce recommender system

Offline recommendation research on Retailrocket interactions. M0–M6 cover ingestion, evaluation, nonpersonalized baselines, ItemKNN, educational MF/BPR, and implicit ALS. M7 candidate generation has not started.

## Current benchmark

The primary M4–M6 comparison is [rolling temporal evaluation](docs/ROLLING_EVALUATION_PROTOCOL.md): nine future windows, a shared historical training snapshot and candidate catalog for every model in each fold, and a warm discovery cohort with at least one prior interaction. Cold users are counted separately. See the [rolling benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) and artifacts in `benchmarks/rolling/`.

The original M3 leave-last-out split produced a 200,028-user test cohort, but its shared training set included future events from other users relative to many targets. Some targets were already seen by their users. Its committed `*_v1` metrics and reports are retained as historical records and cannot be compared to the rolling results. The single-cutoff experiment previously called v2 has been removed. The current benchmark is named **rolling**; there is no published v2 or v3 benchmark release.

The nine-fold reference results were inspected before the rolling sweeps were locked. They are **diagnostic, configs transferred** from historical experiments. Sweeps select on folds 1–4 and report folds 5–9, but those later folds are not a blind holdout; see the report for the exact limitation.

## Reproduce

Activate the existing `ecommerce-recsys` Conda environment, then run from the repository root:

```powershell
python -m pip install -e ".[dev]"
python scripts/build_interactions.py
python scripts/prepare_rolling_data.py
python scripts/sweep_rolling.py --model item_knn
python scripts/sweep_rolling.py --model als
python scripts/benchmark_rolling.py
python scripts/benchmark_rolling_cold.py
python -m pytest tests -q
ruff check .
ruff format --check .
```

The raw dataset belongs in `data/raw/`; see [data/raw/README.md](data/raw/README.md). If `interactions.parquet` and raw CSVs are in another checkout, skip `build_interactions.py` and pass their paths with `--input-path` and `--raw-dir` to `prepare_rolling_data.py`. Pass `--input-path` to both sweep commands and both benchmark commands too. Generated raw/processed data are ignored by Git; the rolling manifest and JSON results are repository artifacts.

The preparation and benchmark commands resume verified checkpoints. The manifest hashes interactions, raw item properties, and each fold file; changing any of these inputs requires a fresh rolling output directory and manifest. Both reference and cold benchmark commands accept `--max-fold 4` for early checks before the two sweeps are complete.

The old `scripts/split_data.py` and single-split benchmark commands use an explicit legacy evaluation mode so they remain runnable. Their per-user split is noncausal at the global level, and model fixes made since the historical runs may change their scores. Use the rolling commands above for current model comparison. See [project status](docs/PROJECT_STATUS.md) for current findings and remaining M7 work.
