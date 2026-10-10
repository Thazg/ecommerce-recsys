# Architecture and engineering decisions

**Updated:** 2026-10-10

This log records decisions applied to the implemented milestones. Records are
grouped by milestone and numbered sequentially from ADR-01. Each record
states the choice, its rationale, the implementation evidence and its limitations.
Planned work is tracked in the [roadmap](ROADMAP.md).

## M0 — Project foundation

### ADR-01 — Implicit-feedback recommendation

**Status:** Accepted

**Decision and rationale:** Predict relevant products from observed behavior,
using views, cart additions and transactions as implicit signals. The dataset
contains behavioral events rather than explicit ratings, so rating regression is
not the task.

**Evidence and consequences:** The canonical interaction schema preserves event
types. Model evaluation uses discovery targets and Top-K metrics. An unobserved
user-item pair is not automatically a negative preference. See the
[data contract](DATA_CONTRACT.md).

### ADR-02 — Reproducible scripts and quality checks

**Status:** Accepted

**Decision and rationale:** Data preparation, fitting and evaluation run through
Python modules and scripts. Notebooks support exploration; they are not the sole
execution path for reported experiments.

**Evidence and consequences:** `scripts/` contains executable pipelines, `tests/`
contains regression tests, and CI runs dependency checks, Ruff and pytest. Dataset
benchmark runs require the external data files; CI uses bounded test fixtures.

### ADR-03 — Introduce package boundaries with implemented functionality

**Status:** Accepted

**Decision and rationale:** Create modules when the corresponding functionality
is implemented. Empty placeholders make the architecture harder to assess.

**Evidence and consequences:** Data, recommendation and evaluation packages cover
M1–M6. The retrieval package is introduced with the M7 implementation. The
[current architecture](ARCHITECTURE_CURRENT.md) describes those code paths.

### ADR-04 — Separate scope, progress, design and measured evidence

**Status:** Accepted

**Decision and rationale:** The charter defines project scope, the roadmap defines
planned milestones, status tracks progress, architecture describes implemented
components, and experiment reports contain measured evidence.

**Evidence and consequences:** These documents have separate responsibilities.
An experiment result belongs in its report; a technical choice and its trade-offs
belong in this log.

### ADR-05 — Repository-defined Python environment

**Status:** Accepted

**Decision and rationale:** Declare Python 3.13, runtime dependencies and quality
checks in repository-controlled configuration. A developer's local environment
alone is insufficient to reproduce the package.

**Evidence and consequences:** [pyproject.toml](../pyproject.toml) defines the
package and pytest import paths; [CI](../.github/workflows/ci.yml) installs the
package and runs checks on Linux. Raw data is obtained separately as documented
in the [reproduction instructions](../README.md#reproduce).

## M1 — Dataset and data contract

### ADR-06 — Retailrocket and a canonical interaction schema

**Status:** Accepted

**Decision and rationale:** Use Retailrocket's timestamped user-item events and
item properties. They support the defined implicit-feedback task and temporal
catalog snapshots. Normalize IDs to strings and preserve millisecond timestamps
and event types.

**Evidence and consequences:** The [dataset card](DATASET_CARD.md),
[data contract](DATA_CONTRACT.md) and
[schema module](../src/ecommerce_recsys/data/schemas.py) define the inputs.
Processed interactions and item metadata are generated from raw CSVs. Raw and
Parquet data are excluded from Git; hashes identify benchmark inputs.

## M2 — Interaction semantics

### ADR-07 — Preserve event types without arbitrary event weights

**Status:** Accepted

**Decision and rationale:** Retain views, cart additions and transactions, without
assigning unsupported numerical ratios such as view=1, cart=3, purchase=5.
Different models use representations appropriate to their objective.

**Evidence and consequences:** Popularity counts event rows; ItemKNN uses distinct
user-item pairs for binary cosine/co-occurrence; ALS aggregates repeated rows in
its sparse implicit matrix. None applies event-type importance multipliers.
The [data-quality report](DATA_QUALITY_REPORT.md) documents the behavioral
funnel. Any weighting experiment must identify the changed representation and
use the shared temporal evaluation.

## M3 — Evaluation and its revision

### ADR-08 — Historical per-user leave-last-out

**Status:** Superseded by ADR-11

**Decision and original rationale:** Hold out the last interaction per eligible
user, with an earlier interaction for validation. This preserved ordering within
each user's history and supplied one target per user.

**Observed limitation:** The combined training set contained other users' events
after many target timestamps, so within-user ordering did not establish global
causality. In addition, 86,949 of the 200,028 historical targets were already seen
by their own users.

**Consequence:** Retain those experiments as historical evidence. They do not
provide the current causal discovery comparison. See the
[historical protocol](EVALUATION_PROTOCOL.md) and
[baseline report](BASELINE_REPORT.md).

### ADR-09 — Shared evaluation before model comparison

**Status:** Accepted

**Decision and rationale:** Compare models on identical temporal snapshots,
targets, catalogs and metric definitions. A score change should reflect the model
rather than a different evaluation population.

**Evidence and consequences:** The recommendation harness reports HR, MRR and
NDCG at 5, 10 and 20, plus coverage and latency. With one target per user-window,
HR@K equals Recall@K. Causality and unseen-target checks precede evaluation.
Source-specific training restrictions do not change the shared target cohort.

### ADR-10 — Preserve benchmark provenance

**Status:** Accepted

**Decision and rationale:** Preserve historical experiment artifacts and make
protocol changes explicit. Do not change targets or cohort rules to improve a
model's reported result.

**Evidence and consequences:** Historical baseline artifacts remain frozen. The
rolling manifest hashes interactions, raw property sources and all fold files;
rolling outputs bind to the complete manifest fingerprint. Checkpoints reject
changed provenance. Scores from incompatible protocols are not placed in a
common model ranking.

### ADR-11 — Global rolling cutoffs with a 4/5 phase allocation

**Status:** Accepted for the current diagnostic benchmark

**Adopted:** 2026-10-04

**Decision:** Construct ten chronological windows and nine evaluation folds.
Each fold trains on all events at or before its cutoff and evaluates the next
window. Use the first unseen target for returning users with at least one prior
interaction. Report first-time users separately. Item categories and candidate
eligibility use only information available at the cutoff.

**Why rolling:** Multiple cutoffs provide repeated future periods while enforcing
`max(train timestamp) < min(target timestamp)` globally. A single cutoff supplies
only one snapshot; the historical per-user split did not enforce this condition.

**Why four development folds and five later folds:** This is a pragmatic
allocation of the nine available periods, with slightly more periods reserved
for evaluating locked configurations. The limited sweeps contain eight distinct
configurations per model; four earlier snapshots provide development evidence
across changing training sizes, with 32 selection rows per sweep. The remaining
five snapshots supply the larger later diagnostic sample. The ratio was not
optimized by comparing split outcomes and is not a statistical guarantee.

| Phase | Folds | Warm user-window targets | Share of warm targets | Role |
| :--- | :--- | ---: | ---: | :--- |
| Development | 1–4 | 30,784 | 34.16% | Select configurations by pooled HR@20, then NDCG@20 for ties |
| Post-selection | 5–9 | 59,323 | 65.84% | Measure locked configurations across later periods |

The 4:5 ratio refers to folds, not users, events or elapsed time. The same user ID
can appear in both phases, while each prediction uses only its available past.
For example, a 6/3 allocation would provide 51,853 selection targets and 38,254
later targets: more development data at the cost of a smaller later sample.
Other allocations are legitimate prospective designs; none was established as
optimal in these experiments. Changing the allocation after inspecting scores
would create another exploratory analysis rather than independent validation.

**Validity limit:** Reference scores for folds 5–9 were viewed before the M5–M6
sweep configurations were locked. Selection uses only folds 1–4, but the later
scores remain post-selection diagnostics. The 4/5 allocation cannot restore
blindness. The one-hit ALS selection margin also illustrates why this allocation
does not guarantee a stable model choice.

**Evidence:** [Rolling protocol](ROLLING_EVALUATION_PROTOCOL.md),
[benchmark report](ROLLING_BENCHMARK_REPORT.md) and
[manifest](../benchmarks/rolling/manifest.json).

## M4 — Baseline models

### ADR-12 — Compare against simple popularity sources

**Status:** Accepted

**Decision and rationale:** Implement Random, Global Popularity, Recent Popularity
and Category Popularity before attributing improvements to collaborative models.
They establish whether a more expensive model adds useful information.

**Evidence and consequences:** Recent popularity uses a 30-day window. Warm and
cold results are separate in the [rolling report](ROLLING_BENCHMARK_REPORT.md).
The small ItemKNN–Category HR@20 difference does not establish a robust winner.
Popularity also supplies a usable recommendation path for first-time users.

## M5 — Item-based collaborative filtering

### ADR-13 — Sparse ItemKNN with support-aware shrinkage

**Status:** Accepted as an offline reference

**Decision and rationale:** Build binary user-item cosine similarities and retain
20 neighbors per eligible item. Require five training interaction rows for item
eligibility. Adjust similarity by `support / (support + lambda)` so low-support
co-occurrences receive less weight.

**Evidence:** The rolling sweep evaluates eight lambda values on folds 1–4.
Lambda 100 is selected by pooled HR@20, with NDCG@20 breaking its tie with 200 and
500. [Sweep artifact](../benchmarks/rolling/item_knn_sweep.json).

**Consequences:** Sparse histories and finite neighbor lists can produce empty or
short pools. The standalone recommender has a popularity fallback for unknown
history; the M7 direct source exposes only collaborative candidates and attributes
popularity to its own source. The earlier experiment is retained in the
[baseline report](BASELINE_REPORT.md).

## M6 — Implicit matrix factorization

### ADR-14 — Educational models and library ALS at scale

**Status:** Accepted as offline model references

**Recorded:** 2026-10-05

**Decision and rationale:** Keep small educational MF/BPR implementations to make
the objective and updates inspectable. Use the `implicit` ALS implementation for
the full sparse interaction dataset. Its learned user/item dot product supplies
scores across the fitted catalog, complementing a finite neighbor graph.

**Evidence:** The eight-configuration rolling sweep covers factors, regularization
and iterations. The documented selection rule chooses 128 factors, 40 iterations
and regularization 0.01. Seed 42 and one numerical worker control repeatability.
[ALS sweep](../benchmarks/rolling/als_sweep.json) and
[historical MF report](MF_EXPERIMENT_REPORT.md).

**Consequences:** ALS trails ItemKNN and Category in the warm Top-20 comparison.
The 40-iteration choice wins roughly one selection hit over 20 iterations, which
is insufficient by itself to justify the extra fitting cost. It remains a fixed
reference for M7 candidate recall. Factor-array size is not full-process memory,
and unknown users have no learned vector.

## M7 — Candidate retrieval

### ADR-15 — Separate candidate retrieval from final ranking

**Status:** Retrieval implemented; learned ranker not implemented

**Decision and rationale:** Request candidate pools at budgets of 100, 500 and
1,000 products, then allow a later ranker to order the available candidates for
Top-K recommendations. These budgets are upper bounds; source availability varies.
Candidate Recall@N measures whether the target is available to that later stage.

```text
Train-time catalog -> Candidate sources -> Eligible pool -> Later ranker -> Top-K
```

**Evidence and consequences:** `retrieval/` implements the shared context and
candidate records. Outputs retain per-source scores and ranks. Candidate metrics
are independent of HR/MRR/NDCG for final recommendations. A ranker cannot recover a
target missing from its input pool.

### ADR-16 — Exact ALS retrieval as the M7 reference

**Status:** Implemented

**Decision and rationale:** Score the fitted item matrix by exact user/item dot
product. Filter training positives and additional seen history before selecting
Top-N, with deterministic item-ID ties. This provides a reference whose quality
and cost can be measured directly.

**Evidence and consequences:** `mf_retriever.py` wraps the fitted ALS model.
Unknown users return an empty direct ALS pool, and exhausted catalogs return
fewer candidates. No ANN engine is selected or added in M7.

### ADR-17 — Source attribution and reciprocal rank fusion

**Status:** Accepted as an offline retrieval reference

**Implemented and measured:** 2026-10-05

**Decision:** Combine ItemKNN, exact ALS, category, recent popularity and global
popularity through a common candidate contract. Each source returns up to 1,000
unique, catalog-eligible, unseen candidates with finite scores. Category retrieval
pools training counts across history categories and has no implicit global
backfill. Personalized sources return empty when their required context is absent.

**Fusion rationale:** Raw model scores have different scales. Retain them as
evidence and use equal-weight reciprocal rank fusion, `sum(1 / (60 + rank))`, to
construct the shared pool. Fix pool depth 1,000 and constant 60 before the M7 run.
Measure a second hybrid without ALS to expose its net recall/cost trade-off.

Ranks refer to each source's eligible, seen-filtered list. Fusion retains those
supplied ranks when it removes additional ineligible cached entries. Personalized
sources can return empty pools; global and recent popularity supply separately
attributed fallback. Source empty rates and hybrid availability are distinct.

**Evaluation and limits:** Use the existing warm/cold cohorts and folds without
changing the 4/5 phase allocation. Report Recall@100/500/1000, reachable-target
recall, availability, coverage, source contribution and retrieval cost. Keep
unreachable targets in the primary denominator. Inherited model settings were
selected for HR@20, not optimized for Recall@1000. These reused periods remain
diagnostic.

**Evidence:** [Candidate-generation plan and contract](CANDIDATE_GENERATION.md)
and the [retrieval report](CANDIDATE_RETRIEVAL_REPORT.md). The complete benchmark
contains 126 comparisons across nine folds and two cohorts. The pooled hybrid
Recall@1000 change from adding ALS is -0.167 percentage points on folds 5–9;
the ablation and per-fold cost qualify that result rather than establishing a
production model choice.
Checkpoint provenance binds the manifest, source data, selected configurations,
code, runtime and retrieval policy. Source fitting, final ranking and API overhead
are excluded from measured retrieval latency.

Linear percentiles use a shared helper. Top-20 recommendation latency, candidate
retrieval at 1,000 and repeated cold-context latency have distinct workloads and
are not directly comparable. See the
[metric and protocol glossary](METRICS_AND_PROTOCOLS.md).

## M8 — Two-tower retrieval

### ADR-18 — Compare two-tower retrieval on shared rolling targets

**Status:** Implemented; M8 v1 development and diagnostic artifacts complete

**Decision and rationale:** Add a deterministic CPU two-tower retriever using
recent distinct item history for the user representation and item ID plus
train-time category for the item representation. Use exact dot-product scoring
over the fold's train-time catalog so candidate recall can be compared directly
with exact ALS without introducing an ANN index or a different target set.

**Causal feature policy:** Training examples use only strictly earlier user
history; every event sharing the positive timestamp is excluded from its
history. The same history encoder is used at training and inference. Model
training is limited to interactions at or before the fold cutoff, and item
categories come from that fold's catalog. Five negatives are sampled uniformly
from catalog items first seen strictly before the positive event, excluding the
positive, the full same-timestamp positive bucket and history. Examples with no
eligible causal negative are skipped and counted instead of aborting the fold.

**Selection:** Compare four two-tower configurations (dimension 64/128 and
history 20/50) and eight existing ALS configurations on folds 1–4. Select by
pooled Recall@1000, then Recall@100, then the predeclared lower-complexity
tie-break. The corrected Two-Tower v1 sweep selected dimension 128 and maximum
history 50 on folds 1–4. The lock binds the development artifact, manifest,
source data, policy and runner fingerprints. The existing ALS v2 sweep selected
128 factors/40 iterations/regularization 0.01 on folds 1–4; its unchanged
development and diagnostic artifacts are SHA-bound into the M8 v1 lock. The
selected Two-Tower and ALS configurations were evaluated on the same 59,323
warm user-windows in folds 5–9. Two-Tower pooled Recall@100/500/1000 was
0.044485/0.096185/0.127640; ALS achieved 0.050705/0.087116/0.109216. Folds 5–9
were previously inspected, so these are post-selection diagnostics and not
blind validation.

**Evidence and consequences:** A review found that negative sampling blocked
only the truncated feature history, allowing an older previously seen item to
be sampled as a negative. The implementation now keeps the full prior seen set
for negative exclusion while retaining truncated history features for the user
tower. A second review found that context deduplication erased event order at
inference, making repeated-item histories differ from training. The M8 path now
retains ordered events for the shared latest-occurrence encoder while preserving
the deduplicated context view used by existing M7 and ALS sources. Refit clears
prior model state, and defensive batch skips are counted separately. The
corrected Two-Tower v1 benchmark completed; prior exploratory metrics are
excluded because the inference history lost event order. ALS v2 artifacts are
reused because the ALS path, deduplicated context, data, runtime and candidate
policy are unchanged; their full artifact SHA and original provenance are
bound into the selection lock. The model is CPU/offline only; no ANN index,
final ranker, cold-user personalization or online serving is implemented.
Reported latency is offline and not a serving SLA.

**Artifacts and implementation:** [two-tower report](TWO_TOWER_REPORT.md),
[versioned development and diagnostic artifacts](../benchmarks/retrieval/),
`retrieval/two_tower.py`, and `scripts/benchmark_two_tower.py`.

## M9 — Approximate retrieval feasibility

### ADR-19 — Do not adopt an ANN index for the current Two-Tower workload

**Status:** Accepted as an offline feasibility no-go; no ANN source promoted to
the retrieval package

**Recorded:** 2026-10-09

**Decision and rationale:** Profile exact Two-Tower retrieval before adding an
index. Exact p95 at a 1,000-candidate request exceeded the declared 10 ms cost
trigger on three of four development folds, permitting an ANN pilot. Compare
Faiss HNSW settings against exact Two-Tower from the same fitted model on the
same sampled warm requests. Require ANN p95 at most half of paired exact p95 on
every development fold before paying index build and memory costs. All four
predeclared settings were slower than exact on fold 1, so none can satisfy that
all-fold gate. Stop without tuning on later periods or adopting an index.

**Evidence and limits:** The [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) and
[exact profile](../benchmarks/retrieval/m9_profile_v1.json) record folds 1–4
costs. The [paired pilot](../benchmarks/retrieval/m9_ann_pilot_v1.json) records
3,000 timed calls per method and configuration on a 1,000-request fold-1 sample.
ANN p95 was 14.844–35.411 ms, versus 9.311–10.698 ms for paired exact. Sample
target hits are diagnostic only; no complete ANN recall sweep or folds 5–9 ANN
evaluation was run. Faiss passed a local Windows smoke test, but Linux CI and
loaded-process RSS were not measured. This no-go concerns this model, catalog,
budget, index grid and machine; it does not rule out ANN for a larger catalog or
a different workload. No serving SLA follows from offline retrieval timing.

## M10 — Causal ranking data

### ADR-20 — Build labelled warm candidate rows from a fixed M7 pool

**Status:** Accepted for development-fold dataset construction

**Recorded:** 2026-10-10

**Decision and rationale:** Use the M7 full hybrid with a 1,000-item budget as
the single M10 candidate source. Its pooled development-fold target recall was
6,717/30,784, compared with 6,590/30,784 for the hybrid without ALS. Regenerate
each request pool from its fold's train-only snapshot and label a candidate only
when it matches that request's first unseen future target. Keep every warm
request in a separate audit table, including catalog-unreachable targets and
catalog-reachable targets absent from the pool. Build features solely from
cutoff-time interactions, as-of categories and retrieved source evidence.

**Evidence and limits:** The [ranking dataset report](RANKING_DATASET_REPORT.md),
[quality artifact](../benchmarks/ranking/m10_quality_v1.json) and
[independent audit](../benchmarks/ranking/m10_feature_audit_v1.json) cover
30,784 warm requests and 30,784,000 candidate rows on folds 1–4. All four
folds reproduced the frozen M7 hit and pool counts; the persisted rows have
no null or nonfinite values. M7's already-inspected folds 5–9 favor the cheaper
hybrid without ALS, so the M10 source choice is a development policy rather
than an independently validated or production-optimal one. The ALS and
ItemKNN configurations were selected on folds 1–4, not folds 5–9; M10's
fold 1–4 recall reuses development-selected retrieval and is in-sample.
M10 does not train
a ranker, evaluate Top-K ranking quality, mix cold users into warm results or
open folds 5–9. M11 must compare rankings on the same fixed pool and keep later
folds labelled as post-selection diagnostics.
