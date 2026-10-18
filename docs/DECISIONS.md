# Architecture and engineering decisions

**Updated:** 2026-10-18

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

**Status:** Accepted; retrieval implemented in M7 and an offline ranker evaluated in M11

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
M10 does not train a ranker, evaluate Top-K ranking quality, mix cold users into
warm results or open folds 5–9. The subsequent learned-ranker experiment
compares orders on the same fixed pool and labels later folds as post-selection
diagnostics.

## M11 — Learned ranking on fixed candidate pools

### ADR-21 — Use a pairwise linear ranker as the offline ordering comparison

**Status:** Accepted for offline evaluation; no production ranker selected

**Recorded:** 2026-10-11

**Decision and rationale:** Reorder the fixed 1,000-item full-hybrid pool with
a deterministic linear pairwise logistic model. Compare its order with the
original RRF order on each exact same candidate list. Use cutoff-time item,
category-affinity and source-evidence features, training-only scaling, and
request-seeded hard/uniform negative sampling. Choose L2 `alpha` from
`0.0001`, `0.001`, and `0.01` by pooled HR@20 on chronological development
folds 2–4, then NDCG@20 and stronger regularization. Bind the chosen
`alpha=0.01` to the complete development artifact before opening the M11
scores for folds 5–9. Fit the final ranker on labelled folds 1–4; keep all
warm requests, including targets absent from the pool, in diagnostic metrics.

**Evidence and limits:** The [learned-ranking report](LEARNED_RANKING_REPORT.md),
[development artifact](../benchmarks/ranking/ranker_development_v1.json),
[selection lock](../benchmarks/ranking/ranker_selection_lock_v1.json) and
[diagnostic artifact](../benchmarks/ranking/ranker_diagnostic_v1.json) record
the policy, fingerprints, per-fold scores and costs. Across 59,323 warm
user-windows in folds 5–9, RRF has 2,285 hits@20 and the ranker 3,237 on the
same regenerated pools; Candidate Recall@1000 remains 12,549/59,323 for
both. The gain is 952 hits, with positive differences in each fold. The
development scores selected `alpha` and can be optimistic. Folds 5–9 were
inspected in earlier milestones, so the later scores are post-selection
diagnostics, not blind validation or statistical-significance evidence. M7
aggregate parity does not prove historical item-by-item pool equality. The
full hybrid retains an expensive ALS source despite a previously observed
no-ALS retrieval advantage on later folds; this comparison does not choose a
production retrieval policy or establish serving latency.

## M12 — Sequential candidate retrieval

### ADR-22 — Keep ordered transitions experimental after the matched ablation

**Status:** Accepted no-go for the tested ordered source; existing hybrid unchanged

**Recorded:** 2026-10-12

**Decision and rationale:** Test whether recency weights on the last interaction
time buckets improve next-window candidate recall over equal weights. Both
policies use one train-only next-bucket transition table, the same 20 selected
buckets, the same train-time catalog, full-history seen filtering and no hidden
fallback. A four-ordered-setting development grid selects lookback 20 and decay
0.8 by pooled hits@100, hits@1000 and fixed simplicity tie-breaks. The
equal-weight comparator is bound at the selected lookback in a separate
SHA-verified lock before M12 diagnostic scoring on folds 5–9.

**Evidence and consequences:** The [sequential report](SEQUENTIAL_RECOMMENDATION_REPORT.md),
[development artifact](../benchmarks/retrieval/sequential_development_v1.json),
[selection lock](../benchmarks/retrieval/sequential_selection_lock_v1.json) and
[diagnostic artifact](../benchmarks/retrieval/sequential_diagnostic_v1.json)
record the policy, fingerprints, integer counts and cost. The ordered policy
found 3,799 targets at 100 candidates versus 3,824 for equal weighting over
59,323 warm user-windows in folds 5–9. Each later fold favored the equal-weight
control at rank 100; both policies found 4,035 by rank 1,000. The predeclared
order-benefit gate failed, so the experimental source is not added to the M7
hybrid. These are post-selection diagnostics because earlier experiments
inspected folds 5–9. The result concerns this direct source and finite grid;
it does not reject other sequential models or establish a serving policy.

## M13 — Category-aware re-ranking

### ADR-23 — Retain a category-novelty bonus as an offline trade-off option

**Status:** Accepted for offline comparison; no production re-ranker selected

**Recorded:** 2026-10-13

**Decision and rationale:** Reorder only the learned ranker's Top-100 candidates
from the fixed full-hybrid pool. Use cutoff-time item categories and a
deterministic utility equal to normalized learned rank plus a bonus for a
known category not yet selected. Unknown categories receive no bonus. The
zero-bonus order must reproduce the learned Top-5/10/20. A fixed grid of
`0`, `0.05`, `0.10` and `0.20` was measured on chronological development
folds 2–4. The predeclared gate required a strict increase in distinct known
category slots@20, with at most `0.001` absolute HR@20 and NDCG@20 loss and
at most `0.005` known-category item-slot loss. The complete development
artifact selected `0.10` and a SHA-bound lock preceded the folds 5–9
diagnostic. This option remains for complete-policy comparison; it is not a
serving decision. The utility uses rank rather than score magnitude and is a
distinct-category re-rank, not an item-distance or aspect-coverage model.
The gate applies to pooled Top-20 only; it does not constrain each fold or
Top-5/10 relevance.

**Evidence and limits:** The [re-ranking report](DIVERSITY_RERANKING_REPORT.md),
[development artifact](../benchmarks/ranking/diversity_development_v1.json),
[selection lock](../benchmarks/ranking/diversity_selection_lock_v1.json) and
[diagnostic artifact](../benchmarks/ranking/diversity_diagnostic_v1.json)
record the policy, integer numerators, costs and provenance. Across 59,323
warm user-windows in folds 5–9, distinct known-category slots@20 rose from
0.125625 to 0.146108, while hits@20 changed from 3,237 to 3,236 and
NDCG@20 from 0.026383 to 0.026135. Catalog item coverage fell slightly in
every fold. The pool stayed fixed at Candidate Recall@1000 of 0.211537.
These later periods were inspected before this experiment; the figures are
post-selection diagnostics, not blind validation or significance evidence.
Incomplete category metadata, the fixed Top-100 shortlist, the costly full
hybrid source and missing online measurements limit generalization. A later
untouched period is needed to confirm a full model-policy choice.

## M14 — Complete offline model-policy comparison

### ADR-24 — Freeze separate warm and cold offline reference routes

**Status:** Accepted offline reference; complete post-selection diagnostics

**Recorded:** 2026-10-13

**Decision and rationale:** Compare eleven fixed warm policies and three cold
policies on shared cutoff snapshots and cohorts. Keep the published retrieval
settings, ranker alpha 0.01 and optional category bonus 0.10. Select each route
on pooled development folds 2–4 by hits@20, NDCG@20 numerator, fewer source
models, smaller bonus and stable name. The complete development comparison
selects full-hybrid learned ordering for warm requests and recent popularity
for cold requests. An explicit SHA-bound lock precedes this benchmark's
diagnostic scoring; later scores cannot change the routes. The reference uses
no category bonus because its development accuracy is lower under this rule.

**Evidence and consequences:** The [policy report](MODEL_POLICY_REPORT.md),
[development artifact](../benchmarks/model_policy/development_v1.json),
[selection lock](../benchmarks/model_policy/selection_lock_v1.json) and
[diagnostic artifact](../benchmarks/model_policy/diagnostic_v1.json) bind the
grid, source/model/data identity and independent cohort choices. Warm selection
has 1,631/25,438 hits@20; cold selection has 4,557/405,518. No-ALS learned
alternatives use unchanged full-hybrid-trained weights and scales; this is
transfer with changed pools and evidence, not pool-specific retraining.
Matched independent inference calls measure retrieval through final ordering;
source fit, feature preparation and factor arrays have separate cost scopes.
The accuracy-first rule has no latency, diversity, per-fold or Top-5/10 gate.
On folds 5–9, full learned has 3,237/59,323 hits@20 versus 3,120 for no-ALS
transfer. The locked cold route has 8,416/715,331 hits@20; popularity RRF has
8,945. The development lock retains recent, while the report discloses RRF's
later HR advantage and recent's higher later NDCG. Full-source fit estimates
range from 301.88–632.22 seconds/fold versus 34.71–115.25 without ALS. These
are the costs of an accuracy-selected reference rather than a serving budget.
Upstream tuning already reused the development period, and folds 5–9 were
inspected earlier. All later measurements remain post-selection diagnostics,
not blind validation. Packaging, HTTP serving, operational fallbacks and online
confirmation remain separate work.

**Provenance verification:** The retrospective
[supplement](../benchmarks/model_policy/provenance_v1.json) records explicit ALS
and ranker-sampling seeds, the independent feature-audit SHA and exact hashes
of the completed policy artifacts. Its verifier checks the existing historical
source chain, audit counts/file hashes and current data without model fitting.
It preserves the original three artifacts and does not extend the original
pre-diagnostic lock retroactively. A cost-constrained choice requires a new
prospective objective and experiment; the accepted accuracy-first route remains
fixed.

## M15 — Versioned offline inference artifacts

### ADR-25 — Package an immutable cutoff snapshot with an independent loader

**Status:** Accepted; complete snapshot and loaded-quality verification

**Decision and rationale:** Persist the locked warm/cold reference as a
versioned snapshot. Use JSON, Parquet and NumPy with pickle disabled, rather
than serializing executable Python training objects. Keep original factor
precision, sorted mappings, full seen sets, KNN similarities/support and all
cutoff-time ranking statistics. A package-native inference scorer preserves
the frozen feature order and transforms without importing training scripts.

**Evidence and consequences:** The [artifact contract](MODEL_ARTIFACTS.md)
defines eleven components, a schema-versioned manifest, input/model/code hashes,
Python major/minor and exact library requirements and an optional externally
pinned manifest digest. OS/architecture changes warn and require host parity
validation. One explicitly reviewed reader predecessor remains supported only
while its prediction implementation fingerprint matches; other stale code is
rejected. This preserves the original manifest and quality receipt.
Inventory/checksum checks precede deserialization, followed by semantic shape,
mapping, finite-value and chronology checks. Staging is sealed before atomic
publication; existing versions cannot be overwritten. Tiny actually fitted
models verify source/evidence/features/scores/output parity, malformed-state
rejection, resume and isolated-process inference with scripts disabled.
The [fold-9 validation receipt](../benchmarks/artifacts/fold09_v1.json) records
101 exact reference traces and complete loaded quality parity with the frozen
policy on 13,539 warm and 142,024 cold targets. These are round-trip and
same-period engineering checks, not new blind accuracy evidence.
The default historical snapshot uses the fold-9 cutoff and the ranker fitted
on labelled folds 1–4. Known users use stored features and their complete seen
set; unknown users take explicit recent popularity. No dynamic-history contract,
HTTP service or deployment claim is introduced. Integrity checks do not provide
publisher authentication; a trusted external manifest digest pins the version.

## M16 — Local snapshot recommendation API

### ADR-26 — Bound HTTP inference around the immutable snapshot

**Status:** Accepted; local HTTP reference verification complete, memory target unmet

**Decision and rationale:** Expose the frozen warm/cold reference through a
separate FastAPI transport and service controller. Load a mandatory
digest-pinned bundle once during lifespan startup; accept only a stored user
ID and strict Top-1–20 budget. Do not accept request-time histories or silently
recover inference errors with popularity. This keeps HTTP behavior distinct
from model selection and the artifact producer.

The frozen numerical adapter changes thread limits process-wide. Run model
work in one dedicated thread with a process-wide admission permit, returning
503 busy on overlap. Keep health routes asynchronous. A cancelled waiter
cannot release admission while its worker runs; graceful shutdown drains
accepted work. Unexpected execution or output-contract failures make the
service unready until restart. The supported launcher has one process, accepts
loopback bindings and has no reload. Cache, public deployment and operational
fallbacks have separate scope.

**Evidence and consequences:** The [API contract](RECOMMENDATION_API.md) defines
the strict schema, bounded JSON parsing, errors and lifecycle. The
[HTTP boundary receipt](../benchmarks/serving/http_boundary_v1.json) binds code, optional
requirements, schema, runtime and the unchanged manifest. A real loopback
process matches 100 warm and one cold reference output, six prefix calls and
an unknown-user cold call; seven invalid requests follow the error contract.
Deterministic tests cover admission across app instances, cancellation,
shutdown, failure cleanup and output guards. Optional HTTP dependencies live
in requirements files because historical experiment fingerprints bind
`pyproject.toml`. Ready RSS is 2.19 GiB, above the 2 GiB charter target.
The sequential warm sample has p95 231.36 ms and p99 303.02 ms; it is not a
concurrent-load or SLA result. Linux full-bundle parity and online accuracy
remain unverified. No model refit or benchmark selection changes are introduced.

## M17 — Bounded cache and explicit overload fallback

### ADR-27 — Make reuse and degraded delivery optional snapshot policies

**Status:** Accepted; reference parity and repeat-sample cache gates pass, memory target unmet

**Decision and rationale:** Add a process-local LRU with insertion TTL and both
entry-count and charged-entry limits. Bind keys to the immutable manifest/policy
and known-user or canonical cold context. Store validated Top-20 output without
request metadata; all K requests use exact prefixes with fresh IDs. Cache
failures disable reuse and leave a healthy primary available. Primary failures
invalidate cache state and require restart.

Keep cache disabled and busy admission rejected by default. An explicit operator
option may return a startup-prepared recent-popularity pool filtered against
the full seen history on busy only. Attribute that response as degraded, with
reason and manifest lineage. Never store it as personalized primary output or
permit it after failed startup/inference or shutdown. No external cache,
request-history updates, queue, hot replacement or automatic recovery is added.

**Evidence and consequences:** The [service contract/report](SERVICE_CACHE_AND_FALLBACKS.md)
and [paired HTTP receipt](../benchmarks/serving/cache_state_validation_v1.json) bind
source, inputs, settings and runtime. Separate off/on processes match 100 warm
and one cold reference on off, miss and hit paths. Warm p95 is 236.69/221.35/1.15
ms respectively; the fixed hit/miss ratio gates pass. Repetition avoids all
additional primary calls. The live cache holds 101 entries and 217,152 charged
bytes; this excludes container/allocator costs and is not an RSS cap. Off/on
sampled peak RSS is 1.93/2.03 GiB, exceeding the 2 GiB target in the cache-on
process. The synthetic repeat workload does not establish
production hit rate, throughput or SLA. Deterministic tests and an actually
fitted tiny snapshot verify busy attribution, full seen filtering, cache faults,
cancellation and shutdown. Event-controlled regressions verify readiness after
permit acquisition, shared startup/shutdown cleanup and fallback-failure
invalidation without releasing another worker's admission. The bounded fallback can return short/empty results;
its warm relevance has not been independently evaluated. Earlier policy/model
artifacts and HTTP receipts remain immutable under their original identities.

## M18 — Local service observability

### ADR-28 — Observe HTTP delivery and primary computation separately

**Status:** Accepted; fixed-schema exporter and failure-isolated event logging implemented

**Decision and rationale:** Give each app an independent registry and expose
Prometheus text 0.0.4 at the local `/metrics` endpoint. Keep fixed enum dimensions
for endpoints, methods, statuses, outcomes, delivery routes/cache, admission and
cache events. Put version and manifest on one loaded-model information sample;
exclude user/item/request IDs, raw URLs and backend errors from metric labels.
Retain bounded histogram buckets and counters rather than per-request samples.

Observe HTTP final-body completion/cancellation independently of numerical worker
execution. A cancelled waiter still owns accepted computation until its worker
releases admission. Cache events remain cumulative after disable, while retained
inventory gauges and point-in-time process RSS have separate resource meanings.
Scrapes do not call models, expire entries or change a faulty cache's state.

The launcher configures an owned JSON event logger with fixed fields and validated
server-generated correlation IDs. Ordinary observer, log-sink and sampling errors
are counted without changing recommendation behavior. Raw payloads, item lists,
paths, exception strings and tracebacks stay outside owned events. Uvicorn/model
library output has a separate review boundary; synchronous stderr may block.

**Evidence and consequences:** The [contract](OBSERVABILITY.md) specifies scope,
dimensions, privacy, histogram boundaries and operational queries. Regression
tests cover independent registries, early HTTP rejects, cancellation versus worker
completion, degraded attribution, live cache counters, memory/sink failures and
redaction. The implementation uses standard-library state/locks and the existing
psutil dependency; no model, upstream benchmark or requirement changes are needed.
It installs no collector, dashboard, alert delivery or public monitoring endpoint,
and provides no new quality, traffic hit-rate or workload-SLO claim.
The [real HTTP receipt](../benchmarks/serving/observability_lifecycle_validation_v1.json)
reconciles normal-path metrics/events against 100 warm/one cold references:
off/on 106/215 HTTP invocations, 102/210 deliveries and no observer errors.
Source/model pins and both cache latency gates pass. Sampled peak RSS is
2.25/2.40 GiB, above the 2 GiB target; uncached p99 is 519.14 ms, above the
initial 500 ms target. These budgets remain separate from the ratio gates.
Owned cleanup records one startup outcome/duration even after repeated caller
cancellation or stop-before-ready. The verifier canonicalizes label sets;
out-of-bounds cache samples are rejected without modifying cache state.
Earlier receipts are preserved under their original source identities.

## M19 — Local input and exposure controls

### ADR-29 — Bound local HTTP input and make shared access explicit

**Status:** Accepted — implemented for loopback API contract 1.2.0.

**Context:** The existing snapshot service bounds numerical work and JSON bytes,
but those controls do not bound incomplete-header sockets, body-read time,
request attempts or browser exposure. Forwarded headers trusted from a local
peer would also undermine a socket-peer limiter. Public deployment is not an
implemented contract.

**Decision:** Keep one loopback process with the unchanged model/cache/failure
semantics. Use a narrow Uvicorn 0.54.0/h11 0.16.0 adapter to cap connections,
enforce header/target budgets before ASGI scope creation and apply absolute
generation-checked header deadlines across keep-alive cycles. Pin compatibility
and reject unaudited upgrades. Disable proxy-header processing explicitly.

Before inference, enforce local Host/same-origin policy, atomic global and
actual-socket-peer token buckets, bounded idle-expiring peer state, optional
shared bearer credentials and bounded body readers with one absolute deadline.
Reject unsupported body routes and close early-denied connections instead of
draining them. Refuse trailer declarations and nonempty chunked trailers before
publishing body completion; ordinary chunked JSON remains supported. Preserve
strict JSON/schema validation, numerical worker ownership
and failure readiness. Default settings are prospective engineering limits;
they were not optimized against diagnostic model results.

Default access remains local anonymous. Operator tokens come from one bounded
environment/file source, stay out of repr/public policy/evidence and use
constant-time comparison. Bearer mode protects readiness/metrics/schema while
leaving minimal liveness public and disabling interactive docs. It grants access
to all snapshot contexts; it is not user/tenant authorization. Neither tokens
nor Host/Origin checks permit external binding or provide TLS.

**Evidence and consequences:** The [contract/report](API_HARDENING.md) defines
limits, denial headers, operational configuration and logging boundaries. Tests
cover policy edges, resource ownership, real incomplete sockets/pipelining and
a fitted tiny snapshot across HTTP. The [real-bundle receipt](../benchmarks/serving/hardening_boundary_validation_v1.json)
pins current service/runner/requirements and the original manifest/reader,
checks 100 warm/one cold off/miss/hit references and reconciles denials,
transport events, worker/delivery counts and owned logs. Both cache ratio gates
pass; sampled ready/peak memory still exceeds 2 GiB. New-connection paced client
timings differ from earlier persistent probes and do not isolate auth/cache cost.
Earlier receipts remain unchanged. No public-security certification, Linux
full-bundle compatibility, production hit rate or workload SLO is established.

## M20 — Integration and functional release verification

### ADR-30 — Separate fixture coverage, model parity and deployment eligibility

**Status:** Accepted — functional gate and explicit integration profiles implemented.

**Context:** Unit faults, finite HTTP receipts and historical loaded-policy
quality answer different questions. A green fixture suite alone does not verify
that the current installed reader and HTTP launcher preserve a particular
Retailrocket snapshot. A passing local model check also cannot establish Linux
compatibility, workload performance or the outstanding resource budgets.

**Decision:** Keep one sequential functional command that checks dependencies,
format/lint, unit regressions, fitted-process integration, explicit isolated
real-bundle references and fresh hardened HTTP evidence. Train only the small
synthetic fixture. Require trusted external manifest and historical quality
pins, verify component inventory, and bind all package/script/test sources and
requirement/CI configuration around execution. Keep earlier model, benchmark
and HTTP receipts unchanged.

Compare the real loader's candidate order, evidence/feature/score digests and
ordered outputs exactly against the sealed producer references. HTTP comparison
uses ordered IDs and model lineage, with separately fresh request IDs. Reject
stale/foreign/partial evidence, unexpected skips, empty profiles and failed or
duplicate JUnit cases. Publish complete fsynced JSON atomically without replacing
an existing receipt; keep logs, JUnit and intermediates outside Git.
Validate profile membership and UTF-8 XML without DTD or entity declarations. Require
the declared HTTP sample counts, finite positive timings and ordered percentiles
before considering cache ratio gates; empty summaries are not evidence.

**Evidence and consequences:** The [strategy](TESTING_AND_RELEASE_GATES.md)
defines commands, test responsibilities, numerical policy and platform limits.
The [functional receipt](../benchmarks/release/integration_boundary_validation_v1.json)
keeps actual profile counts and fresh loader/HTTP evidence separate from the
externally pinned historical quality result. Windows process tests demonstrate
stop/restart; owned graceful drain remains controlled unit coverage, while the
POSIX integration path requests SIGTERM cleanup. CI configures unit and fitted
process checks without a full Retailrocket bundle. `functional_passed` can be
true while `deployment_eligible` remains false: Linux full-bundle, representative
load, target recovery and the 2 GiB memory budget are independent gates. This
work creates no release tag, container, model refit or public endpoint.
