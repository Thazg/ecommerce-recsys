# Current architecture

**Updated:** 2026-10-11
**State:** offline pipeline, recommendation evaluation, hybrid candidate generation,
exact Two-Tower retrieval, an ANN feasibility no-go and causal ranking
data for development folds 1–4. A learned ranker has been evaluated offline
on the same regenerated candidate pools in folds 5–9. No production ranker,
ANN production source or online serving process is implemented.

```text
Retailrocket raw CSV
    -> build_interactions.py
    -> interactions.parquet
    -> prepare_rolling_data.py (nine future windows)
    -> data/rolling/fold_XX (warm/cold targets and train-time catalogs)
       + benchmarks/rolling/manifest.json (boundaries and input hashes)

Prepared folds + manifest
    -> sweep_rolling.py -> selected ItemKNN and ALS sweep artifacts
    -> benchmark_rolling.py -> benchmarks/rolling/results.json
    -> benchmark_rolling_cold.py -> benchmarks/rolling/cold.json

Prepared folds + manifest + completed sweeps
    -> benchmark_candidates.py -> benchmarks/retrieval/candidates.json

Prepared folds + manifest
    -> benchmark_two_tower.py (Two-Tower development folds 1–4)
    -> lock_two_tower_configs.py (binds unchanged ALS v2 evidence)
       -> benchmarks/retrieval/m8_selection_lock_v1.json
    -> benchmark_two_tower.py (Two-Tower diagnostic folds 5–9)
    -> benchmarks/retrieval/two_tower_diagnostic_v1.json

Prepared folds + published Two-Tower selection lock
    -> profile_exact_retrieval.py (development exact-cost profile)
    -> benchmark_ann_feasibility.py (paired fold-1 Faiss HNSW speed screen)
    -> benchmarks/retrieval/m9_profile_v1.json
       + benchmarks/retrieval/m9_ann_pilot_v1.json (no-go)

Prepared folds + selected hybrid source policy and sweeps
    -> build_ranking_dataset.py (warm development folds 1–4)
    -> data/ranking/m10_v1/fold_XX (request and candidate Parquet, ignored by Git)
       + benchmarks/ranking/m10_quality_v1.json (hash-bound checkpoint)
    -> verify_ranking_dataset.py
       + benchmarks/ranking/m10_feature_audit_v1.json

Verified development ranking rows
    -> benchmark_ranker.py development (train earlier folds, score folds 2–4)
    -> ranker_development_v1.json -> benchmark_ranker.py lock
    -> ranker_selection_lock_v1.json
    -> benchmark_ranker.py diagnostic (fit ranker on folds 1–4;
       regenerate each fold's full-hybrid pool at its cutoff, score folds 5–9)
    -> ranker_diagnostic_v1.json (post-selection, not blind)
```

`src/ecommerce_recsys/data/splitting.py` contains rolling time windows and global causality guards. `src/ecommerce_recsys/data/catalog.py` constructs train-time item and category snapshots. Cohort and metric rules are in the [rolling evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md).

`src/ecommerce_recsys/recommendation/` contains Random, Global Popularity, Recent Popularity, Category Popularity, ItemKNN, ALS, and educational MF/BPR implementations. ItemKNN indexes eligible interaction items and uses popularity fallback for unknown history. ALS uses the `implicit` library. None of these models is wrapped in an online serving process.

`src/ecommerce_recsys/evaluation/` computes HR@K, MRR@K, NDCG@K, catalog coverage, and recommendation-call latency. Its rolling benchmark harness rejects training data that overlaps evaluation time globally, checks unseen targets, and removes previously seen items from global popularity recommendations. Latency excludes training, data loading, network time, and API overhead.

## Candidate retrieval

```text
Fitted train-time snapshot + user/history context
    -> ItemKNN / exact ALS / category / recent / global sources
    -> catalog and seen-item filtering
    -> source candidate pools (requested budget up to 1,000; sources may return fewer)
    -> reciprocal-rank fusion and deduplication
    -> candidates with per-source scores and ranks
```

`src/ecommerce_recsys/retrieval/` defines the common candidate interface and its
adapters. ALS retrieves by exact user/item dot product. The hybrid retains source
evidence and includes explicit popularity sources for cold or sparse context.
Candidates feed the offline learned-ranker experiment described below; no
learned production ranker or HTTP serving process is present.

`evaluation/candidates.py` measures Recall@100/500/1000, reachable-target recall,
empty/full pool rates, candidate counts, coverage and source contribution. The
rolling candidate runner also records source fitting time, ALS factor-array
bytes and retrieval latency. Hybrid latency includes constituent source calls
and fusion, excluding downstream ranking and API overhead. The runner verifies
the complete rolling manifest and selected sweeps, then writes atomic fold
checkpoints bound to code, runtime and retrieval policy.

The [candidate-generation design](CANDIDATE_GENERATION.md) defines source behavior
and benchmark limitations. The
[retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) contains the complete nine-fold
source comparison and cost measurements. Category candidates pool training counts across the
history's categories; this differs from the historical category recommender's
category-order traversal and implicit global backfill.

## Two-tower retrieval

`src/ecommerce_recsys/retrieval/two_tower.py` implements a CPU two-tower model.
The user tower mean-pools shared item-ID embeddings for recent distinct history
items; the item tower combines its item-ID embedding with its category embedding
from the fold's train-time catalog. Both towers project to L2-normalized vectors,
scored by dot product. Training examples use each user's first occurrence of a
novel item after strictly earlier history; all events at the positive timestamp
are excluded from that history. Five uniform negatives are sampled from items
that were in the train catalog strictly before the positive event.

The same latest-occurrence history encoder is used for training and Two-Tower
inference. `RetrievalContext.ordered_history` preserves the event order needed
by that encoder; its existing deduplicated `history` view stays unchanged for
hybrid and ALS sources. Unknown categories use a reserved bucket. Training is
deterministic on CPU with seed 42, one Torch thread, three epochs and fixed
batches; no future fold events enter training.
The benchmark compares exact catalog scoring at candidate budgets 100, 500 and
1,000 against exact ALS on the same warm targets and cutoff catalogs. Folds 1–4
select configurations; folds 5–9 are post-selection diagnostics, not blind
validation. Cold users have no personalized history representation and are not
pooled into the Two-Tower warm results. See the [two-tower report](TWO_TOWER_REPORT.md) and
[two-tower artifacts](../benchmarks/retrieval/).

## ANN feasibility

The experimental `scripts/faiss_ann_adapter.py` queries a Faiss HNSW index built
from the fitted Two-Tower item vectors, then re-scores its shortlist with exact
Two-Tower dot products and applies the shared candidate contract. This adapter
was used only for a local paired fold-1 pilot. The exact-cost profiler covers
development folds 1–4. All four predeclared ANN settings failed the paired p95
speed gate on fold 1, so the pipeline still uses exact retrieval references; no
ANN source is exposed through `src/ecommerce_recsys/retrieval/` or the hybrid
candidate generator.
Faiss is not a project dependency because Linux compatibility CI has not run.
The [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) describes the evidence and limits.

Published two-tower and ANN artifacts bind the source at commit
`7b27f141f8d1a331bc4ebe0e924db59eeeef9e42`. The current semantic script
names produce new runner fingerprints. Reproduce the frozen artifacts from
that commit; write future runs to distinct artifact paths.

## Ranking dataset

`src/ecommerce_recsys/ranking/dataset.py` derives cutoff-time user, item,
event-type and category-affinity features and keeps hybrid source evidence
as separate score, rank and presence fields. The builder refits the fixed hybrid
sources on each fold's verified training snapshot, writes one request row per
warm target and streams up to 1,000 candidate rows per request. Future target
fields are labels/audit metadata and are excluded from the predictor contract.
Unreachable and retrieved-miss targets remain in the request table.

The development builder permits folds 1–4 only and checks its hit, candidate
count and empty-pool totals against the frozen candidate-retrieval artifact.
It writes Parquet files outside Git and atomically checkpoints their SHA-256
hashes. A separate verifier reopens every file and checks counts, ranks,
source evidence and finite features. The
[ranking dataset report](RANKING_DATASET_REPORT.md) records 30,784 warm
requests, 30,784,000 candidate rows, build cost and limitations. The dataset
builder itself never writes folds 5–9; the ranker runner generates their rows
in memory after its configuration is locked.

## Learned ranking

`scripts/learned_ranker.py` implements a deterministic linear pairwise logistic
ranker using cutoff-time candidate features. Positive targets are compared
with deterministic hard and sampled negatives from their own request pools.
The model uses training-only RMS scales, L2 regularization and score/item-ID
tie-breaking. Fold 2 scores use fold 1 training rows; fold 3 uses folds 1–2;
fold 4 uses folds 1–3. `scripts/benchmark_ranker.py` selects regularization
from those development scores and requires a SHA-bound lock before scoring
folds 5–9. The final model fits labelled folds 1–4 once; retrieval sources
are refit separately for each diagnostic fold's cutoff. The RRF and learned
orders are measured on each request's identical candidate list, retaining
zero-positive requests in the denominator.

The [learned-ranking report](LEARNED_RANKING_REPORT.md) documents pooled and
per-fold Top-K metrics, cost scope, and validity limits. The five later folds
are post-selection diagnostics because those periods were inspected in earlier
experiments. The ranker is not deployed as a service.

## Model engineering and trade-offs

| Area | Current finding | Detail |
| :--- | :--- | :--- |
| ItemKNN neighbors | Binary user-item cosine, top 20 neighbors, minimum five interactions, support-aware shrinkage | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| ItemKNN shrinkage | Lambda 100 selected on folds 1–4; 100, 200, and 500 tie on pooled HR@20, with NDCG breaking the tie | [ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json) |
| ALS capacity | 128 factors and 40 iterations selected; its one-hit selection advantage over 20 iterations is weak relative to extra fitting cost | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| Factor memory | Earlier estimate: 399.41 MiB at 64 factors and 798.81 MiB at 128 factors for factor arrays, excluding full process memory | [MF report](MF_EXPERIMENT_REPORT.md) |
| Latency | Local per-call measurement only; see fold-level coverage and p95 latency in rolling artifacts | [Reference results](../benchmarks/rolling/results.json) |

The rolling scripts can resume after interruption. The manifest hashes the interactions source, raw item properties, and each fold Parquet file; the runners verify these hashes before using cached results. ALS training and rolling benchmark calls use one numerical worker thread for repeatability. The result artifacts disclose that folds 5–9 are post-selection diagnostics, not blind validation.

The benchmark uses identical folds and target users for every warm-user model. See [project status](PROJECT_STATUS.md) for current results and the next milestone. The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier model experiments.
