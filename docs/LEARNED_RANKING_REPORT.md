# Learned ranking on fixed candidate pools

## Task and comparison

The ranker reorders the fixed full-hybrid candidate list for each returning
user's first unseen item in a later rolling window. Each request has one target
and at most 1,000 eligible, unseen candidates. The comparison keeps the exact
same candidate list for the learned order and the original reciprocal-rank
fusion (RRF) order. A target absent from the pool cannot be recovered by either
order; such requests remain in the primary metric denominator. Cold first-time
users are outside this experiment.

The [ranking dataset report](RANKING_DATASET_REPORT.md) documents the
cutoff-time feature and label contract. The ranker uses the development
Parquet for folds 1–4. For later-fold diagnostics, it regenerates each fold's
candidate list and features from that fold's training snapshot in memory.
Every later fold must match the published [retrieval reference](../benchmarks/retrieval/candidates.json)
on target hits in pool, candidate count and empty requests before its result
is accepted.

## Model and selection

A linear pairwise logistic model scores each candidate. Training pairs subtract
the feature vector of a sampled candidate from the vector of the one observed
future target. Unobserved candidates are sampled comparison items, not proven
dislikes. Each positive request contributes its first 20 RRF negatives and up
to 80 request-seeded samples from the remaining candidates. Requests without
a positive candidate do not contribute training pairs but remain in every
evaluation denominator.

The model transforms counts and nonnegative recencies with `log1p`, source
ranks with `1 / (60 + rank)`, and signed source scores with signed `log1p`.
It uses cutoff-time item, category-affinity and retrieval-source evidence;
target metadata, labels and IDs are excluded from predictors. Training-pair
RMS scales are learned only from earlier folds. User-only fields are constant
within a request and cancel from pairwise differences; they are retained in
the dataset schema for other ranking models. Model fitting uses one numerical
worker, deterministic L-BFGS and a maximum of 100 iterations. Scores sort
descending, with ascending item ID resolving exact ties.

Development comparison is chronological: train on fold 1 and score fold 2;
train on folds 1–2 and score fold 3; train on folds 1–3 and score fold 4. The
rolling manifest places each training fold's evaluation end at or before the
next fold's training cutoff, so those labels are available by the time the
next fold is scored. The
regularization grid was fixed at `0.0001`, `0.001`, and `0.01`. Selection uses
pooled HR@20, then pooled NDCG@20, then the larger regularization value.
The [development artifact](../benchmarks/ranking/ranker_development_v1.json)
records all three settings, per-fold metrics and optimization status.

| Evaluation fold | Warm requests | Target in pool | RRF hits@20 | Selected ranker hits@20 | RRF HR@20 | Ranker HR@20 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 7,201 | 1,659 | 283 | 497 | 0.039300 | 0.069018 |
| 3 | 8,602 | 1,826 | 338 | 536 | 0.039293 | 0.062311 |
| 4 | 9,635 | 2,056 | 398 | 598 | 0.041308 | 0.062065 |
| **Pooled 2–4** | **25,438** | **5,541** | **1,019** | **1,631** | **0.040058** | **0.064117** |

The pooled selected-ranker hit count and rate above are calculated from the
integer per-fold numerators. The selected `alpha=0.01` is bound to the complete
development artifact by the
[selection lock](../benchmarks/ranking/ranker_selection_lock_v1.json).
This ranker comparison keeps evaluation requests out of ranker training.
The fold 2–4 scores also select `alpha`, so the selected configuration's
development gain is a tuning result and can be optimistic.
However, the ItemKNN/ALS settings and full-hybrid candidate policy were
selected using folds 1–4. Development retrieval quality is consequently an
in-sample construction diagnostic, not an independent estimate for the full
pipeline.

## Post-selection diagnostic on folds 5–9

The selected `alpha=0.01` model was fit once on labelled folds 1–4 and then
scored without refitting on folds 5–9. The
[diagnostic artifact](../benchmarks/ranking/ranker_diagnostic_v1.json) is
complete and binds the selection lock, model coefficients, code and input
fingerprints. All five rebuilt pools reconcile with M7's aggregate target-hit,
candidate-count and empty-request totals. M7 does not store individual
candidate lists, so that parity check does not establish item-by-item equality
with the historical artifact. The RRF and learned orders **within this run**
use each request's identical regenerated list.

The primary denominator is all **59,323 warm user-windows**. Exactly **12,549**
targets are in the 1,000-candidate pool, giving Candidate Recall@1000 of
**0.211537**. The other requests contribute zero to all ranking metrics.

| Fold | Warm requests | Target in pool | RRF hits@20 | Ranker hits@20 | RRF HR@20 | Ranker HR@20 | RRF MRR@20 | Ranker MRR@20 | RRF NDCG@20 | Ranker NDCG@20 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 10,349 | 2,300 | 425 | 636 | 0.041067 | 0.061455 | 0.014023 | 0.020695 | 0.020013 | 0.029654 |
| 6 | 10,720 | 2,293 | 429 | 603 | 0.040019 | 0.056250 | 0.014910 | 0.018643 | 0.020427 | 0.026903 |
| 7 | 11,950 | 2,510 | 467 | 654 | 0.039079 | 0.054728 | 0.013244 | 0.018784 | 0.018908 | 0.026696 |
| 8 | 12,765 | 2,692 | 480 | 675 | 0.037603 | 0.052879 | 0.011246 | 0.017188 | 0.017000 | 0.025023 |
| 9 | 13,539 | 2,754 | 484 | 669 | 0.035749 | 0.049413 | 0.012074 | 0.017374 | 0.017299 | 0.024478 |
| **Pooled 5–9** | **59,323** | **12,549** | **2,285** | **3,237** | **0.038518** | **0.054566** | **0.012984** | **0.018427** | **0.018597** | **0.026383** |

At Top-20, the ranker finds **952 more targets** than RRF on the same pools,
an absolute HR difference of **0.016048** (1.605 percentage points after
rounding). Every diagnostic fold has a positive hit difference. These are
descriptive post-selection results; repeated users across windows and prior
inspection of folds 5–9 prevent a blind-holdout or significance claim.

The next table shows pooled metrics at all declared output budgets. Each
pooled value weights its fold by warm-request count. HR and Recall are equal
because this task has one target per request.

| Order | K | Hits | HR/Recall@K | MRR@K | NDCG@K | HR@K given target in pool |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| RRF | 5 | 1,151 | 0.019402 | 0.011127 | 0.013177 | 0.091720 |
| Ranker | 5 | 1,649 | 0.027797 | 0.015801 | 0.018769 | 0.131405 |
| RRF | 10 | 1,657 | 0.027932 | 0.012247 | 0.015917 | 0.132042 |
| Ranker | 10 | 2,374 | 0.040018 | 0.017420 | 0.022708 | 0.189178 |
| RRF | 20 | 2,285 | 0.038518 | 0.012984 | 0.018597 | 0.182086 |
| Ranker | 20 | 3,237 | 0.054566 | 0.018427 | 0.026383 | 0.257949 |

The conditional column divides hits by the **12,549 targets in the pool**,
not by all 59,323 requests. Conditional MRR/NDCG at each K are also in the
diagnostic artifact. Per-fold metrics at K=5 and K=10 are below; the full
integer hit numerators are in the artifact.

| Fold | K | RRF HR | Ranker HR | RRF MRR | Ranker MRR | RRF NDCG | Ranker NDCG |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 5 | 0.021741 | 0.030534 | 0.012122 | 0.017668 | 0.014508 | 0.020860 |
| 6 | 5 | 0.021735 | 0.028545 | 0.013183 | 0.015984 | 0.015297 | 0.019086 |
| 7 | 5 | 0.019163 | 0.027699 | 0.011287 | 0.016102 | 0.013237 | 0.018974 |
| 8 | 5 | 0.016843 | 0.026244 | 0.009245 | 0.014578 | 0.011134 | 0.017453 |
| 9 | 5 | 0.018391 | 0.026664 | 0.010370 | 0.015118 | 0.012355 | 0.017979 |
| 5 | 10 | 0.030341 | 0.044352 | 0.013267 | 0.019488 | 0.017287 | 0.025305 |
| 6 | 10 | 0.029478 | 0.039925 | 0.014189 | 0.017503 | 0.017773 | 0.022766 |
| 7 | 10 | 0.028117 | 0.041004 | 0.012477 | 0.017849 | 0.016128 | 0.023249 |
| 8 | 10 | 0.026009 | 0.038073 | 0.010452 | 0.016171 | 0.014081 | 0.021293 |
| 9 | 10 | 0.026516 | 0.037743 | 0.011417 | 0.016570 | 0.014945 | 0.021535 |

## Measurement scope and limitations

The diagnostic artifact records four cost components per fold. `fit_seconds`
times fitting the five retrieval sources. `retrieval_seconds` sums full-hybrid
candidate-generation calls; `feature_seconds` sums per-request feature-row
construction; `scoring_seconds` sums DataFrame conversion, feature transforms,
linear scores and the target-rank calculation. These are sequential local
offline timings. They exclude data loading, training the final ranker, fold
feature-aggregate construction, request-history preparation, persistence,
networking and an API. They are neither an end-to-end serving latency nor a
serving SLA.

| Fold | Retrieval-source fit seconds | Retrieval-call sum seconds | Feature-row sum seconds | Ranking-score sum seconds |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 273.0 | 352.5 | 266.5 | 109.3 |
| 6 | 308.5 | 373.8 | 266.8 | 109.7 |
| 7 | 374.7 | 435.9 | 297.5 | 122.2 |
| 8 | 409.2 | 486.8 | 317.7 | 130.9 |
| 9 | 458.3 | 546.8 | 337.9 | 138.7 |

The source uses ALS even though the previously inspected folds 5–9 favored a
cheaper hybrid without ALS at candidate Recall@1000. This experiment isolates
whether learning to reorder the **fixed full-hybrid pool** helps Top-K ranking;
it does not establish that the source policy minimizes cost or maximizes
end-to-end quality. Folds 5–9 were inspected before this ranker was selected,
so their results are post-selection diagnostics, **not blind validation**.
Independent confirmation requires a later, untouched time period. No
statistical-significance or production-readiness claim follows from these
offline comparisons.

## Reproduction

Prepare the rolling dataset and selected ItemKNN/ALS sweeps, build and verify
the ranking dataset, then run these commands from the repository root in the
Python 3.13 `ecommerce-recsys` environment:

```sh
python scripts/benchmark_ranker.py development
python scripts/benchmark_ranker.py lock
python scripts/benchmark_ranker.py diagnostic
pytest
ruff check .
ruff format --check .
```

The `development` runner accepts only the complete folds 1–4 M10 checkpoint.
The `lock` step binds its selected configuration. The `diagnostic` step refuses
to score folds 5–9 without that lock, verifies the rolling input/fold files,
and writes atomic fold checkpoints. Later-fold candidate rows are generated in
memory; the large Parquet files from development remain outside Git. The
published JSON includes full policies, hashes, selected model weights, runtime
versions, per-fold counts and metric numerators. Raw Retailrocket files are
not re-read by the ranker runner; their source hashes are inherited through
the rolling manifest and upstream artifacts.
