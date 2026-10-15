# E-commerce recommendation system

An offline recommendation project built on the Retailrocket interaction dataset. The repository contains data preparation, temporal evaluation, popularity baselines, ItemKNN, educational MF/BPR, implicit ALS, source-aware candidate retrieval and learned ranking with locked warm/cold reference routes. Online serving is not implemented.

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

The candidate-retrieval benchmark evaluates retrieval separately from final
Top-K ranking. Each source is asked
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

A deterministic CPU two-tower retriever compares its exact catalog
scores with ALS on the same rolling warm targets. The model uses recent distinct
item history on the user side and item ID plus train-time category on the item
side. Negative sampling excludes the full prior user history, including items
outside the truncated feature history. The selected Two-Tower configuration
(dimension 128, history 50) achieved pooled Recall@100/500/1000 of
0.044485 / 0.096185 / 0.127640 on 59,323 warm user-windows in folds 5–9. ALS
achieved 0.050705 / 0.087116 / 0.109216 on the same targets. The period had
been inspected before configuration lock, so these are post-selection
diagnostics, not blind validation. See the [two-tower report](docs/TWO_TOWER_REPORT.md)
for per-fold metrics, cost, latency scope and provenance.

## ANN feasibility

The ANN feasibility study screened approximate search against exact Two-Tower
retrieval before adding an index to the candidate pipeline. Exact p95 exceeded
the predeclared cost trigger on three of four development folds. In a paired
fold-1 Faiss HNSW pilot, all four
index configurations were slower than exact at the 1,000-candidate budget, so
none met the predeclared speed gate. No ANN index was adopted, and no folds 5–9
ANN results are reported. The [ANN feasibility report](docs/ANN_RETRIEVAL_REPORT.md)
shows the timing, sample-hit and index-build evidence with its limitations.

## Causal ranking dataset

The ranking pipeline builds candidate-level training data for the warm rolling
task on development folds 1–4. The fixed full hybrid generated
**30,784,000 candidate rows** for **30,784 warm user-windows**. Of those
requests, 6,717 have their future target
in the 1,000-item pool (Candidate Recall@1000 **0.218198**). Requests with an
unreachable or unretrieved target remain in the denominator. Features use only
the fold's training snapshot and as-of catalog; an independent Parquet audit
found no null or nonfinite values. The dataset build itself stops before
learned Top-K evaluation. The [ranking dataset report](docs/RANKING_DATASET_REPORT.md)
records the feature contract, per-fold counts, build cost and reproduction steps.

## Learned ranking

A deterministic pairwise linear ranker uses the labelled development rows and
reorders the same fixed 1,000-candidate full-hybrid pool as RRF. Its L2 setting
was selected on chronological folds 2–4, then locked before scoring folds
5–9. On **59,323 warm user-windows** in those later folds, RRF had **2,285**
hits@20 (HR@20 **0.038518**) and the ranker had **3,237** (HR@20
**0.054566**). The pool itself reached **12,549** targets (Candidate
Recall@1000 **0.211537**); the ranker changes ordering, not retrieval.
All five later folds improved in hit count. These are **post-selection
diagnostics, not blind validation**, and the offline experiment does not
select a production retrieval or serving policy. The
[learned-ranking report](docs/LEARNED_RANKING_REPORT.md) covers per-fold
HR/MRR/NDCG, selection, cost and limitations.

## Category-aware re-ranking

A fixed category-novelty bonus reorders the learned ranker's Top-100 shortlist
without changing its candidate pool or scores. The bonus was selected on
chronological folds 2–4 and locked before the folds 5–9 diagnostic. On the
same **59,323 warm user-windows**, distinct known-category slots@20 increased
from **0.125625** to **0.146108**, while Top-20 hits changed from **3,237** to
**3,236** and NDCG@20 from **0.026383** to **0.026135**. Item catalog coverage
fell slightly in every fold; Top-5 hits fell from **1,649** to **1,638**.
The rule uses learned rank and category counts, without item-distance or
aspect-probability modeling. This is an offline relevance/diversity trade-off,
not a deployed ranking policy. The later folds are **post-selection
diagnostics, not blind validation**. The [re-ranking report](docs/DIVERSITY_RERANKING_REPORT.md)
gives the denominator, per-fold metrics, cost and limitations.

## Sequential retrieval experiment

A train-time next-bucket transition source tested whether giving more weight
to recent interaction buckets improves candidate order. On the same **59,323
warm user-windows** in folds 5–9, the locked ordered policy found **3,799**
targets at 100 candidates (Recall@100 **0.064039**); its equal-weight control
using the same 20 buckets found **3,824** (Recall@100 **0.064461**). Both found
**4,035** by 1,000 candidates. The predeclared order-benefit gate failed, so
the source was not added to the hybrid. These are post-selection diagnostics,
not blind validation. The [sequential report](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md)
documents the temporal contract, ablation, per-fold results and cost scope.

## Offline reference policy

The complete-policy comparison locks separate routes on development folds 2–4:
full-hybrid learned ordering for returning users and recent popularity for
first-time users. Eleven warm and three cold alternatives share their cutoff
snapshots, cohorts and output budgets. The complete folds 5–9 diagnostic has
3,237/59,323 warm hits@20 for the locked route (HR@20 0.054566) and
8,416/715,331 cold hits@20 (HR@20 0.011765). Cold popularity RRF has more
later hits than the locked recent route; the development choice remains fixed.
These are post-selection diagnostics on previously inspected periods. The
[policy report](docs/MODEL_POLICY_REPORT.md) records selection,
no-ALS model transfer, availability and matched inference-cost scope. This is
an offline reference; artifact packaging and online serving are not implemented.

## Repository guide

- [Rolling evaluation protocol](docs/ROLLING_EVALUATION_PROTOCOL.md): cohorts, time boundaries, selection rule, and validity limits.
- [Benchmark report](docs/ROLLING_BENCHMARK_REPORT.md) and [result artifacts](benchmarks/rolling/): measured outcomes and per-fold data.
- [Current architecture](docs/ARCHITECTURE_CURRENT.md) and [project status](docs/PROJECT_STATUS.md): implemented components and next steps.
- [Roadmap](docs/ROADMAP.md) and [candidate-generation design](docs/CANDIDATE_GENERATION.md): milestone scope, retrieval contracts and validation gates.
- [Dataset card](docs/DATASET_CARD.md) and [data contract](docs/DATA_CONTRACT.md): source, schema, and processing assumptions.
- [Engineering decisions](docs/DECISIONS.md): design rationale, including the transition from per-user leave-last-out to global temporal folds.
- [Metric and protocol glossary](docs/METRICS_AND_PROTOCOLS.md): comparison boundaries, units, model references and latency workloads.
- [ANN feasibility report](docs/ANN_RETRIEVAL_REPORT.md): conditional index decision and measured no-go result.
- [Ranking dataset report](docs/RANKING_DATASET_REPORT.md): causal ranking rows, feature contract and development-fold audit.
- [Learned-ranking report](docs/LEARNED_RANKING_REPORT.md): same-pool Top-K comparison, model selection and diagnostic limits.
- [Category-aware re-ranking report](docs/DIVERSITY_RERANKING_REPORT.md): locked same-pool diversity trade-off, relevance and cost.
- [Sequential retrieval report](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md): matched order ablation and measured no-go decision.
- [Offline policy report](docs/MODEL_POLICY_REPORT.md): complete fixed-policy comparison, warm/cold route lock and matched cost scope.

Earlier leave-last-out experiments remain in the [baseline](docs/BASELINE_REPORT.md) and [MF](docs/MF_EXPERIMENT_REPORT.md) reports as historical evidence. Their scores answer a different evaluation question and should not be compared directly with the rolling results.

## Reproduce

Use Python 3.13 from the repository root. Download the
[Retailrocket dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)
and extract `events.csv`, `category_tree.csv`, `item_properties_part1.csv` and
`item_properties_part2.csv` into `data/raw/`. Alternatively, with an authenticated
Kaggle CLI, run `python scripts/download_data.py`. Verify the files with
`python scripts/download_data.py --verify-only`. The [dataset card](docs/DATASET_CARD.md)
describes the source, schema and recorded input hashes. In a fresh checkout,
prepare the shared rolling inputs and candidate reference with:

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

The raw CSVs and generated Parquet files are not committed. If they reside
elsewhere, pass `--input-path` and `--raw-dir` to the preparation command, and
`--input-path` to the sweep and benchmark commands. The manifest records
SHA-256 hashes for the processed interactions, raw item properties, and each
generated fold file; runners verify those hashes before resuming.

The published M10/M11 artifacts bind an earlier source tree. Later package
additions changed their broad source fingerprints without changing their
original implementation. To regenerate the frozen ranking Parquet inputs, use a
separate full-history checkout at Git revision
`c80cebee3378ea9af7c9757802fa40e2c8594ae2` with the matching processed
interactions and rolling fold files. Copy the matching frozen benchmark JSON
from the current checkout as well: their byte serialization is part of the
checksum chain. Then run:

```sh
python -m pip install -e ".[dev]"
python scripts/build_ranking_dataset.py --artifact .local/ranking_rebuild_v1.json
python scripts/verify_ranking_dataset.py --quality benchmarks/ranking/m10_quality_v1.json --output .local/ranking_rebuild_audit_v1.json
```

Use a fresh scratch checkpoint for a rebuild; the published checkpoint resumes
only when its generated files already exist and match their hashes. The verifier
above checks rebuilt Parquet against the frozen file hashes. Preserve published
JSON, whose checksums also bind the original measured costs. A different runtime
or serialization may require a separately named experiment rather than a
byte-identical reproduction.

With those verified M10 Parquet files and published M10/M11 JSON artifacts
available, return to the current checkout and reinstall its editable package
before running the category-aware experiment:

```sh
python -m pip install -e ".[dev]"
python scripts/benchmark_diversity.py development
python scripts/benchmark_diversity.py lock
python scripts/benchmark_diversity.py diagnostic
python scripts/benchmark_model_policy.py development
python scripts/benchmark_model_policy.py lock
python scripts/benchmark_model_policy.py diagnostic
python scripts/verify_model_policy.py
```

The runner verifies the historical source revision and upstream hashes; it
does not rewrite frozen artifacts. The [ranking dataset](docs/RANKING_DATASET_REPORT.md),
[learned ranking](docs/LEARNED_RANKING_REPORT.md), [re-ranking](docs/DIVERSITY_RERANKING_REPORT.md),
[offline policy](docs/MODEL_POLICY_REPORT.md)
and [sequential](docs/SEQUENTIAL_RECOMMENDATION_REPORT.md) reports give each
experiment's commands, artifact paths and scope.
