# Current architecture

**Updated:** 2026-10-05
**State:** offline pipeline and recommendation evaluation; M7 candidate generation has not started.

```text
Retailrocket raw CSV
    -> build_interactions.py
    -> interactions.parquet
    -> prepare_rolling_data.py (nine future windows)
    -> per-fold warm/cold targets and train-time catalogs
    -> benchmark_rolling.py (shared M4–M6 model comparison)
    -> benchmarks/rolling/manifest.json and results.json
```

`src/ecommerce_recsys/data/splitting.py` contains rolling time windows and global causality guards. `src/ecommerce_recsys/data/catalog.py` constructs train-time item and category snapshots. Cohort and metric rules are in the [rolling evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md).

`src/ecommerce_recsys/recommendation/` contains Random, Global Popularity, Recent Popularity, Category Popularity, ItemKNN, ALS, and educational MF/BPR implementations. ItemKNN indexes eligible interaction items and uses popularity fallback for unknown history. ALS uses the `implicit` library. None of these models is wrapped in an online serving process.

`src/ecommerce_recsys/evaluation/` computes HR@K, MRR@K, NDCG@K, catalog coverage, and recommendation-call latency. Its benchmark harness rejects training data that overlaps evaluation time globally, checks unseen targets, and removes previously seen items from global popularity recommendations. Latency excludes training, data loading, network time, and API overhead.

## M5–M6 engineering and model trade-offs

| Area | Current finding | Detail |
| :--- | :--- | :--- |
| ItemKNN neighbors | Binary user-item cosine, top 20 neighbors, minimum five interactions, support-aware shrinkage | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| ItemKNN shrinkage | Lambda 100 selected on folds 1–4; 100, 200, and 500 tie on pooled HR@20, with NDCG breaking the tie | [ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json) |
| ALS capacity | 128 factors and 40 iterations selected; its one-hit selection advantage over 20 iterations is weak relative to extra fitting cost | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| Factor memory | Earlier M6 estimate: about 418 MB at 64 factors and 836 MB at 128 factors for factor arrays, excluding full process memory | [MF report](MF_EXPERIMENT_REPORT.md) |
| Latency | Local per-call measurement only; see fold-level coverage and p95 latency in rolling artifacts | [Reference results](../benchmarks/rolling/results.json) |

The rolling scripts can resume after interruption. The manifest hashes the interactions source, raw item properties, and each fold Parquet file; the runners verify these hashes before using cached results. ALS training and rolling benchmark calls use one numerical worker thread for repeatability. The result artifacts disclose that folds 5–9 are post-selection diagnostics, not blind validation.

The benchmark uses identical folds and target users for every warm-user model. See [project status](PROJECT_STATUS.md) for measured results and the next milestone. The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier model experiments.
