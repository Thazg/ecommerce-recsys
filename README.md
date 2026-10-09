# E-commerce recommendation system

An offline recommendation project built on the Retailrocket interaction dataset. The repository contains data preparation, temporal evaluation, popularity baselines, ItemKNN, educational MF/BPR, implicit ALS and source-aware candidate retrieval. Online serving is not implemented.

## Recommendation evaluation

Benchmark accuracy and coverage use fractions in `[0, 1]`. The
[metric and protocol glossary](docs/METRICS_AND_PROTOCOLS.md) defines units,
evaluation populations, ALS configurations, fallback behavior and timing scopes.

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

## Candidate retrieval

M7 evaluates retrieval separately from final Top-K ranking. Each source is asked
for up to 1,000 eligible, unseen products; this is a request budget, not a
guarantee that every source can fill it. In folds 5–9, ItemKNN returned a mean
of 40.07 products and an empty pool for 14.61% of warm requests. Reciprocal rank
fusion combines available source lists while retaining source scores and ranks.
The same **59,323 warm targets**
in folds 5–9 give the following post-selection diagnostic results:

| Generator | Recall@100 | Recall@500 | Recall@1000 |
| :--- | ---: | ---: | ---: |
| Exact ALS | 0.050705 | 0.087116 | 0.109216 |
| Hybrid without ALS | 0.081183 | 0.165180 | 0.213206 |
| Hybrid | 0.079750 | 0.163832 | 0.211537 |

These figures measure target availability within the candidate pool, not final
Top-20 accuracy. The [retrieval report](docs/CANDIDATE_RETRIEVAL_REPORT.md) covers
all seven generators, cold users, availability, ALS ablation and fitting/retrieval
cost. The [design](docs/CANDIDATE_GENERATION.md) specifies the candidate contract.

## Two-tower retrieval

M8 adds a deterministic CPU two-tower retriever and compares its exact catalog
scores with ALS on the same rolling warm targets. The model uses recent distinct
item history on the user side and item ID plus train-time category on the item
side. Negative sampling excludes the full prior user history, including items
outside the truncated feature history. The selected Two-Tower configuration
(dimension 128, history 50) achieved pooled Recall@100/500/1000 of
0.044485 / 0.096185 / 0.127640 on 59,323 warm user-windows in folds 5–9. ALS
achieved 0.050705 / 0.087116 / 0.109216 on the same targets. The period had
been inspected before configuration lock, so these are post-selection
diagnostics, not blind validation. See the [M8 report](docs/TWO_TOWER_REPORT.md)
for per-fold metrics, cost, latency scope and provenance.

## ANN feasibility

M9 screened approximate search against exact Two-Tower retrieval before adding an
index to the candidate pipeline. Exact p95 exceeded the predeclared cost trigger
on three of four development folds. In a paired fold-1 Faiss HNSW pilot, all four
index configurations were slower than exact at the 1,000-candidate budget, so
none met the predeclared speed gate. No ANN index was adopted, and no folds 5–9
ANN results are reported. The [M9 feasibility report](docs/ANN_RETRIEVAL_REPORT.md)
shows the timing, sample-hit and index-build evidence with its limitations.

## Repository guide

- [Rolling evaluation protocol](docs/ROLLING_EVALUATION_PROTOCOL.md): cohorts, time boundaries, selection rule, and validity limits.
- [Benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) and [result artifacts](benchmarks/rolling/): measured outcomes and per-fold data.
- [Current architecture](docs/ARCHITECTURE_CURRENT.md) and [project status](docs/PROJECT_STATUS.md): implemented components and next steps.
- [Roadmap](docs/ROADMAP.md) and [candidate-generation design](docs/CANDIDATE_GENERATION.md): milestone scope, retrieval contracts and validation gates.
- [Dataset card](docs/DATASET_CARD.md) and [data contract](docs/DATA_CONTRACT.md): source, schema, and processing assumptions.
- [Engineering decisions](docs/DECISIONS.md): design rationale, including the transition from per-user leave-last-out to global temporal folds.
- [Metric and protocol glossary](docs/METRICS_AND_PROTOCOLS.md): comparison boundaries, units, model references and latency workloads.
- [M9 ANN plan](docs/M9_ANN_PLAN.md) and [feasibility report](docs/ANN_RETRIEVAL_REPORT.md): conditional index decision and measured no-go result.

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
python scripts/benchmark_candidates.py
pytest
ruff check .
ruff format --check .
```

The raw CSVs and generated Parquet files are not committed. If they reside elsewhere, pass `--input-path` and `--raw-dir` to the preparation command, and `--input-path` to the sweep and benchmark commands. The manifest records SHA-256 hashes for the processed interactions, raw item properties, and each generated fold file; runners verify those hashes before resuming.
