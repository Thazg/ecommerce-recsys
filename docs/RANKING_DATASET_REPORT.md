# Ranking dataset: causal features and labels

**Status:** Development folds 1–4 completed and independently audited on
2026-10-10. No learned ranker or later-fold ranking diagnostic exists.

## Scope and decision

The dataset contains labelled candidate rows for the warm discovery task in the
[rolling temporal protocol](ROLLING_EVALUATION_PROTOCOL.md). It uses the fixed
full hybrid at a budget of 1,000 candidates, retaining its five source
scores, eligible-list ranks and explicit popularity contribution. The
source choice and feature contract were fixed before this build. On development
folds 1–4, the full hybrid found 6,717/30,784 targets at 1,000 candidates versus 6,590/30,784 without
ALS. Folds 5–9 were previously inspected and favor the cheaper variant; this
choice is an offline development policy, not a production recommendation.
The ALS and ItemKNN sweep artifacts selected configurations on folds 1–4,
not folds 5–9. The candidate policy was also chosen using folds 1–4, so the
Recall@1000 below is an in-sample construction diagnostic rather than an
independent estimate of retrieval quality.

Each fold trains retrieval on interactions at or before its global cutoff and
labels only the first unseen target in the later window. A row is positive when
the retrieved item equals that target. The label is a future interaction, not
an observed negative preference for every other candidate. Requests with a
target outside the training catalog or absent from the retrieved pool remain in
the request table and the primary denominator. Cold first-time users are outside
this dataset and remain a separate cohort.

## Data and reachability

The quality artifact stores integer counts by fold. Candidate Recall@1000 is
`positive candidate rows / all warm request rows`. A target in the catalog but
absent from the pool is a retrieval miss; a target outside the catalog is
unreachable under the train-only policy. These categories are reported
separately. This dataset has no learned-ranker Top-K score.

| Fold | Warm requests | Candidate rows | Reachable targets | Positive rows | Candidate Recall@1000 | Unreachable | Reachable but unretrieved |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5,346 | 5,346,000 | 3,937 | 1,176 | 0.219978 | 1,409 | 2,761 |
| 2 | 7,201 | 7,201,000 | 5,959 | 1,659 | 0.230385 | 1,242 | 4,300 |
| 3 | 8,602 | 8,602,000 | 7,367 | 1,826 | 0.212276 | 1,235 | 5,541 |
| 4 | 9,635 | 9,635,000 | 8,434 | 2,056 | 0.213389 | 1,201 | 6,378 |
| **Pooled 1–4** | **30,784** | **30,784,000** | **25,697** | **6,717** | **0.218198** | **5,087** | **18,980** |

The published candidate-retrieval artifact contains only aggregate results.
The builder regenerated candidate lists and compared each fold's hits,
candidate count and empty-request count to the
[candidate-retrieval artifact](../benchmarks/retrieval/candidates.json)
before accepting its checkpoint. This does not turn the later folds into a blind
holdout. The builder does not generate their candidate-level data.

## Feature and file contract

The ignored `data/ranking/m10_v1/fold_XX/` directory contains
`requests.parquet` and `candidates.parquet`. The former has one row per warm
target, including zero-positive requests; the latter has one row per returned
candidate with a one-based hybrid rank and binary label. The compact
[quality artifact](../benchmarks/ranking/m10_quality_v1.json) binds the input
manifest, raw-property hashes, selected sweeps, candidate-retrieval reference,
policy, feature schema, runtime, code fingerprint, per-fold file hashes and
counts.
Its `data_sha256` identifies fold counts and persisted file hashes independently
of fit/build times and sampled RSS. `payload_sha256` additionally protects the
complete checkpoint record, including those measured costs.

Features use only cutoff-time information: RRF rank/score and source evidence,
user and item interaction counts, event-type counts, recency relative to the
declared global cutoff, and user history in the candidate's as-of category.
Absent source evidence uses an explicit presence flag, rank sentinel 1,001 and
score sentinel 0. Raw source scores remain separate because they have different
scales. Target item and timestamp, label, user/item IDs and fold ID are kept for
joins and audits, but the feature contract excludes them from learned predictors.
Any future scaler or imputer must fit on ranker-training folds only.

## Build cost and verification

Build time includes retrieval model fitting, feature aggregation, candidate
generation and Parquet writing. The recorded RSS is the largest sampled process
working set at build checkpoints; it is not a whole-process high-water mark or
an online serving memory requirement. Parquet bytes are compressed file sizes.

| Fold | Build seconds | Candidate Parquet MiB | Sampled peak RSS MiB |
| ---: | ---: | ---: | ---: |
| 1 | 377.4 | 111.68 | 989.1 |
| 2 | 584.5 | 153.59 | 1,260.4 |
| 3 | 780.7 | 198.18 | 1,465.6 |
| 4 | 914.5 | 225.82 | 1,679.4 |

The independent [feature audit](../benchmarks/ranking/m10_feature_audit_v1.json)
reopens persisted files, checks SHA-256 hashes, row and label totals, consecutive
ranks, null and nonfinite values, source flags/ranks/scores and the request
denominator. Its counts must reconcile with the quality artifact. Unit and
integration tests exercise cutoff boundaries, seen filtering, missing category,
zero-positive requests, atomic output and altered checkpoints.

The audit found **zero null values and zero nonfinite numeric values** across
30,784,000 candidate rows. It recorded 7,427,370 candidate rows with unknown
as-of category (fraction **0.241274** of candidate rows); the feature table
represents these with `category_known = 0` and a zero category-affinity count.
The four compressed candidate files total approximately 689.27 MiB. The sum
of per-fold build times is approximately 2,657 seconds; these are sequential
offline build costs on the recorded local machine, not request latency.

## Reproduction and limitations

Run in the Python 3.13 `ecommerce-recsys` environment after preparing the
rolling folds and the completed ItemKNN/ALS sweeps:

```sh
python scripts/build_ranking_dataset.py
python scripts/verify_ranking_dataset.py
pytest
ruff check .
ruff format --check .
```

The builder accepts `--input-path` and `--fold-dir` when local data lives
outside the checkout. It refuses folds 5–9 until a ranker configuration lock
exists. A learned-ranker evaluation must train on earlier labelled folds,
compare with the RRF order on the **same candidate pool**, and report Top-K
accuracy over all evaluated warm requests. Later-fold results remain
post-selection diagnostics, not blind validation. This dataset build does not
measure learned-ranker quality or serving latency.

A separately predeclared no-ALS source ablation is warranted for ranker cost and
quality analysis because the already inspected later folds favored that
cheaper source. This source has a different candidate pool and must report its
own recall and fit cost. It cannot replace the locked same-pool ranker
comparison after later-fold ranking scores are viewed.
