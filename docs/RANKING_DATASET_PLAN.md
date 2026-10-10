# Ranking dataset plan

**Status:** M10 development dataset and feature pipeline implemented on folds
1–4. The [ranking dataset report](RANKING_DATASET_REPORT.md) records measured outputs and
checks. A learned final ranker remains M11 work.

## Goal and boundary

M10 turns a fixed retrieval pool into reproducible, labelled candidate rows for
the warm rolling task. It defines the request, label and feature contracts,
generates development-fold data, and audits the resulting dataset. M11 will train
and select a ranker, compare Top-K outcomes, and run locked later-fold
diagnostics. M10 makes no claim of ranking improvement.

The [roadmap](ROADMAP.md) groups M10–M11 as the ranking stage. This plan follows
the [rolling protocol](ROLLING_EVALUATION_PROTOCOL.md), the
[candidate contract](CANDIDATE_GENERATION.md), and the
[M7 measured artifact](../benchmarks/retrieval/candidates.json). The M9
[no-go result](ANN_RETRIEVAL_REPORT.md) leaves exact Two-Tower as an experimental
reference; M10 does not add an ANN index or use it as an unmeasured source.

| In M10 | Deferred to M11 |
| :--- | :--- |
| Freeze a candidate source, feature schema and label definition | Choose and train a learned ranker |
| Build and validate folds 1–4 candidate-level data | Select model parameters on chronological development comparisons |
| Report candidate reachability, rows, missing values and build cost | Compare HR/MRR/NDCG@5/10/20 against the same-pool retrieval ordering |
| Provide a guarded generator for later folds | Run locked folds 5–9 post-selection diagnostics |

## Population, source and label

The primary population is the existing **warm discovery** cohort: one first
unseen future item per user-window, with each fold's training data ending at its
declared global cutoff. Folds 1–4 contain 30,784 warm targets. Cold first-time
users require a separate context and policy; M10 will not mix them into the warm
ranking dataset. A later cold ranking experiment must state its own source,
features and denominator.

Use the M7 **full hybrid** at a fixed budget of 1,000 as the primary source. It
fuses ItemKNN, exact ALS, category, recent popularity and global popularity with
the existing equal-weight RRF policy. This choice is declared here using only
the M7 development-fold pooled Recall@1000: full hybrid **0.218198**
(6,717/30,784) versus hybrid without ALS **0.214072** (6,590/30,784). The
full hybrid's higher fit and retrieval cost must be reported. M7's already
inspected folds 5–9 favor the version without ALS; therefore neither this choice
nor later-fold M10/M11 results can be presented as independent blind validation.
Do not revise the source after viewing M11 later-fold metrics. A future cheaper
source can be studied as a separately named ablation with its own frozen policy.

The M7 JSON stores aggregate metrics, **not per-request candidate lists**.
Regenerate each pool from that fold's verified training snapshot, selected model
configurations and `RetrievalContext`. Preserve the generator's output order,
source evidence, full seen-item filtering, train-time catalog and as-of category
metadata. Do not insert the future target into the pool, backfill a missed target,
or add a hidden fallback. Direct sources may be empty; the hybrid's popularity
sources are explicit.

For request key `(fold_index, user_id)`, let `target_item_id` be the already
defined rolling target. A candidate row has `label = 1` exactly when its item ID
equals that target, otherwise `0`. Each request has at most one positive row.
The label describes a **future first unseen interaction**, not a purchase or a
general relevance judgment. A request whose target is outside the cutoff catalog
or absent from the retrieved pool has zero positive candidate rows. Keep that
request in the request table and in the primary evaluation denominator. Report
catalog-unreachable and catalog-reachable-but-unretrieved misses separately.

## Data contract

Write two linked datasets per fold. `request_id` is a stable digest of the fold
and normalized user ID; it is a join key, not a model feature. IDs remain strings.
The request table contains one row per warm target, including empty and
zero-positive pools. The candidate table contains one row per returned candidate.

| Table | Required fields | Purpose |
| :--- | :--- | :--- |
| `requests` | `request_id`, `fold_index`, `user_id`, `cutoff`, `target_item_id`, `target_timestamp`, `target_in_catalog`, `target_in_pool`, `pool_size` | Audit all targets and denominators; target fields are never ranker features |
| `candidates` | `request_id`, `fold_index`, `item_id`, `retrieval_rank`, `label`, feature columns | Train/score a fixed retrieved pool; one unique item per request |

Validate `0 <= pool_size <= 1000`, unique request keys and candidate items,
strictly positive one-based retrieval ranks with no gaps, finite numeric
features, and at most one positive per request. The number of candidate rows for
each request must equal `pool_size`; `target_in_pool` must equal the sum of its
labels. The pooled target-hit count must reproduce a fresh same-code M7 source
evaluation on the same folds. If historical M7 counts differ because source code
or inputs changed, fail or publish an explicit provenance explanation; do not
silently rewrite the historical artifact.

The full hybrid averaged 1,000 candidates on development folds 1–4, implying
**30,784,000 candidate rows** before any training-only sampling. Treat this as a
capacity estimate, verify it during generation, and stream by fold and request
batch. Never build the whole table as one in-memory DataFrame.

## Feature contract

Every feature must be computable at the fold cutoff from its training snapshot,
candidate evidence or fixed policy. No evaluation-window events, target item,
target timestamp, label, or other users' future events may enter feature
computation. The cutoff is the **global fold cutoff**, not `train.timestamp.max()`
when a gap exists. Do not pass `user_id`, `item_id`, `fold_index` or `request_id`
as learned features in M11; retain them only for joins, audits and grouped
evaluation.

| Family | Initial M10 features | Source and missing-value rule |
| :--- | :--- | :--- |
| Retrieval | RRF score, one-based hybrid rank, source count | Existing candidate record; rank and score are separate features |
| Source evidence | Per-source present flag, eligible-list rank and raw score for the five fixed sources | `SourceEvidence`; absent source gets a presence flag of 0 and a documented numeric sentinel, never a fabricated rank 0 |
| User history | Training event count, distinct seen-item count, days since last training event, counts by event type | Training interactions at or before cutoff; no target-window history |
| Item history | Training interaction count, distinct training-user count, days since last training event, event-type counts | Training interactions at or before cutoff; zero for an eligible item without a particular event type |
| User–item context | Candidate category seen in prior user history, count of prior events in that category | Category mappings as-of cutoff; explicit `category_known` flag and zero count when missing |

Keep raw source scores separate: cosine, ALS and popularity counts have different
scales. Do not sum or normalize them using statistics computed from folds that
will be evaluated later. Define units and types in a versioned feature schema;
use a finite sentinel for absent source ranks/scores and a separate missingness
flag. If M11 learns a scaler or imputer, fit it on its ranker-training folds
only. Feature generation should expose an as-of dependency for every column so
future-only data can be tested directly.

## Chronological use of the dataset

M10 generates and publishes **development folds 1–4 only**. Its output is
labelled training material and a data-quality audit, not an accuracy result for
a learned ranker. The generator must refuse folds 5–9 unless a future M11
selection lock binds the candidate policy, feature schema, training procedure
and chosen ranker configuration.

The ItemKNN and ALS sweep artifacts select configurations using folds 1–4,
not folds 5–9. M7 also chose the full hybrid using folds 1–4, so M10's
Recall@1000 on those same folds is an in-sample construction diagnostic. It
must not be used as an independent estimate of retrieval quality. M11's
chronological ranker comparisons avoid training the ranker on its evaluation
fold, but still inherit this development-selected candidate policy.

The intended M11 development evaluation is prequential: train a ranker on fold
1 labels and evaluate on fold 2; train on folds 1–2 and evaluate on fold 3;
train on folds 1–3 and evaluate on fold 4. Fold 1 supplies training data but
no ranker validation score. After selection on these development comparisons,
fit the locked procedure on folds 1–4 and generate/score folds 5–9 without
changing the policy. These later periods were already inspected by prior
milestones, so label all results **post-selection diagnostics, not blind
validation**. Independent confirmation needs a new, previously unseen period.

Full candidate rows are required for validation and later scoring because the
ranker must order the same pool it would receive at inference. M11 may define a
deterministic, training-only negative sampler to control fit cost. Its policy,
seed, positive retention and excluded zero-positive group counts must be
frozen before model selection; it must not change the full-pool evaluation
denominator. M10 should provide a streaming, stable input contract rather than
preselect a sampler based on later ranking scores.

For every evaluated request, compare the learned order with the M7 RRF order
**within the identical candidate pool**. Report pooled and per-fold
HR/Recall@5/10/20, MRR@5/10/20 and NDCG@5/10/20 with all warm targets in the
primary denominator. Also report these metrics conditional on `target_in_pool`
as a diagnostic, always naming that smaller denominator. Candidate Recall@1000
is an upper bound for same-pool HR@20; distinguish retrieval misses from ranking
misses. Measure row-feature generation, model fit and ranking latency separately
from retrieval and from any future end-to-end service latency.

## Implementation sequence and acceptance evidence

| Phase | Work | Exit evidence |
| :--- | :--- | :--- |
| 0. Freeze policy | Record source, budget, feature schema, label, fold guard and provenance inputs. | Reviewed M10 policy object and schema before generating measured rows. |
| 1. Small fixture | Implement request/candidate records and as-of feature extraction on a tiny temporal fixture. | Tests for cutoff, same-timestamp events, categories, repeated history, missing source evidence and zero-positive requests. |
| 2. Development builder | Refit/reuse the fixed M7 source per fold, stream candidate rows, and write request/candidate Parquet partitions for folds 1–4. | Atomic per-fold outputs with hashes and deterministic resume; bounded peak memory. |
| 3. Audit | Reconcile request counts, label sums, target reachability, source evidence, nulls and feature ranges. | `m10_quality_v1.json` with integer totals and per-fold rates; reproduction command and measured build cost. |
| 4. Documentation | Document the dataset contract and ranker split/guard without training a ranker. | Ranking dataset report and updated status/architecture after outputs exist. |

Candidate and request Parquet files belong under ignored `data/ranking/m10_v1/`.
Only compact, verified manifests and quality summaries belong under
`benchmarks/ranking/` in Git. The first valid ranking-dataset artifact uses
`v1`; local pilots and failed runs under `.local/` are not version history.
Keep the published candidate-retrieval, Two-Tower and ANN artifacts frozen.

## Provenance, failure handling and verification

The manifest must bind the rolling manifest and per-fold file SHA-256 values,
processed interactions and raw property hashes, cutoff/catalog identity, M7
source configuration and RRF policy, selected ItemKNN/ALS sweep identities,
feature schema/policy, relevant source fingerprints, package/runtime versions,
and output file hashes. Record row counts, positive counts, unreachable counts,
missing-feature counts, build seconds and peak process memory by fold. Write to
temporary files and atomically replace verified outputs. Resume only when every
input, policy, code and output hash matches; reject partial or mixed-version
partitions.

Tests must cover a target outside the catalog; reachable target omitted from
the pool; empty pool; duplicated candidate; nonfinite evidence; a future-only
interaction or category change that leaves features unchanged; a train event at
the cutoff; same-timestamp ordering; source score/rank alignment; deterministic
ties and reruns; corrupt output or changed hash; and refusal to generate later
folds without an M11 lock. A miniature end-to-end fixture should reconstruct
the request/candidate tables and check all count invariants. Run the relevant
tests and full `pytest`, `ruff check .`, and `ruff format --check .` in the
`ecommerce-recsys` Python 3.13 environment before publishing results.

The implemented outputs are recorded in the [ranking dataset report](RANKING_DATASET_REPORT.md),
[current status](PROJECT_STATUS.md) and [architecture](ARCHITECTURE_CURRENT.md).
Keep [the roadmap](ROADMAP.md) focused on milestone goals.
