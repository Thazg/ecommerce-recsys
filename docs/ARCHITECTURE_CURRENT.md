# Current architecture

**Updated:** 2026-10-15
**State:** offline pipeline, recommendation evaluation, hybrid candidate generation,
exact Two-Tower retrieval, an ANN feasibility no-go and causal ranking
data for development folds 1–4. A learned ranker, category-aware re-ranker
and separate sequential transition source have been evaluated offline. The
sequential order ablation failed its primary gate, so no source was adopted.
A complete-policy runner has locked separate warm/cold offline routes from
development folds 2–4 and completed all fixed diagnostics on folds 5–9.
All routes remain offline; no ANN production source or online serving process
is implemented.
The artifact layer now separates fitted offline snapshots from package-only
inference; it preserves the locked reference without adding a service.

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

Prepared rolling folds + processed train interactions
    -> benchmark_sequential.py development (six transition policies, folds 1–4)
    -> sequential_development_v1.json -> benchmark_sequential.py lock
    -> sequential_selection_lock_v1.json
    -> benchmark_sequential.py diagnostic (matched ordered/equal control, folds 5–9)
    -> sequential_diagnostic_v1.json (order-benefit gate failed; no source adopted)

Fixed learned-ranker scores + fold cutoff category snapshots
    -> benchmark_diversity.py development (category-novelty grid, folds 2–4)
    -> diversity_development_v1.json -> benchmark_diversity.py lock
    -> diversity_selection_lock_v1.json
    -> benchmark_diversity.py diagnostic (fixed Top-100 shortlist, folds 5–9)
    -> diversity_diagnostic_v1.json (same-pool learned-order control)

Verified source snapshots + locked ranker/category settings
    -> benchmark_model_policy.py development (eleven warm/three cold policies)
    -> benchmarks/model_policy/development_v1.json
    -> benchmark_model_policy.py lock -> selection_lock_v1.json
    -> benchmark_model_policy.py diagnostic (folds 5–9, atomic checkpoints)
    -> diagnostic_v1.json (complete flag records finished fold coverage)
    -> verify_model_policy.py -> provenance_v1.json (retrospective seed/audit verification)
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
Candidates feed the offline learned-ranker experiment described below. Its
frozen scorer is also used by the snapshot adapter; no HTTP service is present.

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

## Category-aware re-ranking

`ranking/diversity.py` greedily reorders the first 100 learned-ranked
candidates for a Top-20 output. It uses only a candidate's category from the
fold's train-time catalog. Known categories not yet in the output receive a
fixed novelty bonus; missing categories receive none. Utility ties preserve
the learned-score and item-ID order. The utility uses learned rank rather
than score magnitude or pairwise item distance. The zero-bonus control
reproduces the learned Top-5/10/20 on each request.

`scripts/benchmark_diversity.py` evaluates a fixed bonus grid on chronological
development folds 2–4, locks one choice, and measures that choice against
zero bonus on the same regenerated pools in folds 5–9. It verifies the
published M10/M11 source revision and input hashes because later additions
to the package changed those earlier runners' broad source fingerprints.
The [re-ranking report](DIVERSITY_RERANKING_REPORT.md) defines the category,
denominator, selection and cost contracts. On folds 5–9, the locked bonus
increased distinct known-category slots@20 from 0.125625 to 0.146108 while
Top-20 hits changed from 3,237 to 3,236 on the same 59,323 warm requests.
This offline comparison does not deploy a re-ranker or select a complete
retrieval policy.

## Sequential transition experiment

`retrieval/sequential.py` builds directed transitions between adjacent,
distinct user/timestamp buckets in each fold's training snapshot. Same-time
items form one unordered bucket. The experimental source scores catalog items
from the user's recent training buckets and filters their complete train-time
history. `scripts/benchmark_sequential.py` compares recency-weighted and
equal-weight bucket scores on the same transition table and lookback. A
development artifact and SHA-bound lock precede the folds 5–9 diagnostic.

The ordered policy had 3,799 hits@100 versus 3,824 for its matched control on
59,323 warm user-windows, so this source was not added to the M7 hybrid. The
[sequential report](SEQUENTIAL_RECOMMENDATION_REPORT.md) gives the fold-level
metrics, measured cost and validity limits. This experiment is a direct
candidate source, separate from M11's fixed-pool ranker.

## Offline reference policy

`scripts/benchmark_model_policy.py` compares complete target-free policy calls
from candidate generation through Top-20 ordering. Development scores use
rankers trained on earlier labelled folds; diagnostics reuse the frozen ranker
trained on folds 1–4. The warm route is full-hybrid learned ordering with no
category bonus. The cold route is explicit recent popularity. These choices
come from the complete development comparison, before this runner's later-fold
scoring, and remain unchanged on resume.

The runner includes direct sources, full/no-ALS RRF, learned ordering and the
fixed category option. No-ALS learned variants transfer the same full-pool
model rather than retrain it. Quality can share source outputs and immutable
features; independent calls on matched request samples measure inference cost.
`evaluation/model_policy.py` validates all-request quality numerators, pools
them separately by cohort and applies the frozen selection rule. The
[policy report](MODEL_POLICY_REPORT.md) records scope and limitations. This is
an offline reference. Its model state can be packaged as described below;
online request routing is not implemented.

`scripts/verify_model_policy.py` checks the completed source/data/lock chain and
the earlier independent feature audit, then records explicit seeds and hashes
in a separate provenance supplement. It performs no model fit and preserves the
original benchmark JSON. The supplement is an evaluation record, without a
serialized model bundle or service loader.

## Versioned model snapshot

`scripts/build_model_artifacts.py` verifies the complete policy provenance and
fits its fixed retrieval sources at one declared cutoff. It persists ALS
factors, mappings, full sparse seen sets, ItemKNN neighbors, category/popularity
state, feature aggregates and frozen ranker weights/scales. A sealed manifest
binds eleven safe-format components to their hashes, shapes/schemas, numerical
environment, code identity and upstream evidence. Generated versions live
outside Git under `artifacts/`; the builder publishes a completed staging
directory with an atomic rename and refuses version overwrites.

`ecommerce_recsys.artifacts.load_bundle` verifies inventory, hashes and semantic
consistency before restoring direct-source adapters. A small package-native
inference scorer implements the published feature transforms. The runtime
imports no benchmark scripts and reads no training data. Known snapshot users
use their full stored seen set and cutoff-time features; unknown users use
explicit recent popularity. The response carries item IDs, route, bundle
version and cutoff. It supports deterministic prefixes from 1 to 20 items.
It still depends on compatible package implementations and numerical libraries.
Python major/minor and library checks are strict; OS/architecture differences
warn. Each component is hashed once before loading. Compatibility with the
original reader is restricted to unchanged prediction code and dependencies.

The [artifact contract](MODEL_ARTIFACTS.md) defines the supported snapshot lookup,
round-trip and loaded-quality checks, resume behavior and limitations. Dynamic
user history, HTTP serving, concurrency, cache and live fallback orchestration
are outside this boundary. A loadable historical snapshot is not a deployment.

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
