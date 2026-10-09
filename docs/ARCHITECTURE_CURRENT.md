# Current architecture

**Updated:** 2026-10-09
**State:** offline pipeline, recommendation evaluation, M7 candidate generation and M8 two-tower retrieval. Online serving is not implemented.

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
    -> lock_m8_configs.py (binds unchanged ALS v2 evidence)
       -> benchmarks/retrieval/m8_selection_lock_v1.json
    -> benchmark_two_tower.py (Two-Tower diagnostic folds 5–9)
    -> benchmarks/retrieval/two_tower_diagnostic_v1.json
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
Candidates can be passed to a later ranker; no learned final ranker or HTTP
serving process is present.

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

## M8 two-tower retrieval

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
M7 and ALS sources. Unknown categories use a reserved bucket. Training is
deterministic on CPU with seed 42, one Torch thread, three epochs and fixed
batches; no future fold events enter training.
The benchmark compares exact catalog scoring at candidate budgets 100, 500 and
1,000 against exact ALS on the same warm targets and cutoff catalogs. Folds 1–4
select configurations; folds 5–9 are post-selection diagnostics, not blind
validation. Cold users have no personalized history representation and are not
pooled into M8's warm results. See the [M8 report](TWO_TOWER_REPORT.md) and
[M8 artifacts](../benchmarks/retrieval/).

## M5–M6 engineering and model trade-offs

| Area | Current finding | Detail |
| :--- | :--- | :--- |
| ItemKNN neighbors | Binary user-item cosine, top 20 neighbors, minimum five interactions, support-aware shrinkage | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| ItemKNN shrinkage | Lambda 100 selected on folds 1–4; 100, 200, and 500 tie on pooled HR@20, with NDCG breaking the tie | [ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json) |
| ALS capacity | 128 factors and 40 iterations selected; its one-hit selection advantage over 20 iterations is weak relative to extra fitting cost | [Rolling report](ROLLING_BENCHMARK_REPORT.md) |
| Factor memory | Earlier M6 estimate: 399.41 MiB at 64 factors and 798.81 MiB at 128 factors for factor arrays, excluding full process memory | [MF report](MF_EXPERIMENT_REPORT.md) |
| Latency | Local per-call measurement only; see fold-level coverage and p95 latency in rolling artifacts | [Reference results](../benchmarks/rolling/results.json) |

The rolling scripts can resume after interruption. The manifest hashes the interactions source, raw item properties, and each fold Parquet file; the runners verify these hashes before using cached results. ALS training and rolling benchmark calls use one numerical worker thread for repeatability. The result artifacts disclose that folds 5–9 are post-selection diagnostics, not blind validation.

The benchmark uses identical folds and target users for every warm-user model. See [project status](PROJECT_STATUS.md) for current results and the next milestone. The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier model experiments.
