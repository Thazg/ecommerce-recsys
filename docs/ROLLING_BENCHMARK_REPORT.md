# Rolling benchmark report, M4–M6

**Date:** 2026-10-05

**Dataset:** Retailrocket processed interactions, SHA-256 `5fdbf3e6b8cfdb80fe0aca1066786ac9c6c72326943f988529accfccfaf77a7e`

**Protocol:** [Rolling evaluation](ROLLING_EVALUATION_PROTOCOL.md)

## Cohort and fold boundaries

Each fold trains on all earlier interactions and evaluates the next window. Boundaries below are UTC dates; exact millisecond timestamps are in [manifest.json](../benchmarks/rolling/manifest.json).

| Fold | Train through | Evaluate through | Warm targets | Cold first-time users |
| ---: | :--- | :--- | ---: | ---: |
| 1 | 2015-05-17 | 2015-05-29 | 5,346 | 141,440 |
| 2 | 2015-05-29 | 2015-06-12 | 7,201 | 138,635 |
| 3 | 2015-06-12 | 2015-06-25 | 8,602 | 132,648 |
| 4 | 2015-06-25 | 2015-07-09 | 9,635 | 134,235 |
| 5 | 2015-07-09 | 2015-07-21 | 10,349 | 147,821 |
| 6 | 2015-07-21 | 2015-08-02 | 10,720 | 138,959 |
| 7 | 2015-08-02 | 2015-08-18 | 11,950 | 144,861 |
| 8 | 2015-08-18 | 2015-09-02 | 12,765 | 141,666 |
| 9 | 2015-09-02 | 2015-09-18 | 13,539 | 142,024 |
| **All** | | | **90,107** | **1,262,289** |

The warm targets represent 71,982 distinct people across all nine folds. Selection folds 1–4 have 30,784 targets from 26,597 people; post-selection folds 5–9 have 59,323 targets from 50,630 people. Some people occur in both phases. Cold users appear only once, in the fold when they first interact. 11.10% of warm targets are not in their fold's training catalog and are unreachable by all train-only models. The unseen-item warm cohort is conditional and is not equivalent to the historical 200,028-user leave-last-out cohort.

In the historical split, 86,949 of 200,028 test targets were already present in their own user's training history, while ItemKNN and ALS exclude seen items. Its shared training set also extends past the earliest test timestamp (2015-09-18 versus 2015-05-03, UTC). Those two differences, plus the rolling warm-history requirement, explain why the historical cohort cannot be preserved as the main causal discovery benchmark.

## Nine-fold reference run

This reference table uses fixed earlier configurations for ItemKNN and ALS. It describes all nine folds; scores from folds 5–9 were visible before the later sweep configurations were locked. Consequently, the post-selection table below is exploratory rather than a blind test.

| Model | HR@20 | MRR@20 | NDCG@20 |
| :--- | ---: | ---: | ---: |
| Random | 0.000044 | 0.000006 | 0.000015 |
| Global Popularity | 0.007558 | 0.001506 | 0.002794 |
| Recent Popularity | 0.008101 | 0.002059 | 0.003366 |
| Category Popularity | 0.041950 | 0.011918 | 0.018461 |
| ItemKNN, shrinkage 100 | 0.045391 | 0.020286 | 0.025991 |
| ALS, 128 factors / 20 iterations | 0.029887 | 0.010458 | 0.014744 |

Per-fold metrics, coverage, and inference latency are in [results.json](../benchmarks/rolling/results.json).

As one illustration on fold 9, ItemKNN covers 19.34% of the training catalog with p95 recommendation-call latency 0.138 ms; ALS covers 1.53% with p95 10.280 ms. These are local inference calls after fitting, not end-to-end serving measurements or pooled latency percentiles.

## Configuration selection and final folds

ItemKNN evaluated shrinkage values 0, 5, 10, 20, 50, 100, 200, and 500 on folds 1–4. Lambda 100 won on pooled HR@20 (0.052138), using NDCG@20 to break its tie with 200 and 500. On folds 5–9, it achieved HR@20 **0.041889**, MRR@20 **0.018687**, and NDCG@20 **0.023962**. [Full ItemKNN sweep](../benchmarks/rolling/item_knn_sweep.json).

The ALS sweep covers eight distinct configurations along the factors, regularization, and iterations axes. The documented pooled HR@20 rule selects 128 factors, 40 iterations, and regularization 0.01 on folds 1–4: HR@20 **0.035440**, versus **0.035408** for 128 factors and 20 iterations. That margin corresponds to about one additional hit among 30,784 targets, so it is too small by itself to justify twice as many training iterations. Its selected configuration scores HR@20 **0.027291**, MRR@20 **0.009456**, and NDCG@20 **0.013385** on folds 5–9. The earlier 128-factor/20-iteration reference configuration scores HR@20 0.027021 on those folds; the small gain does not by itself justify the extra fitting cost. [Full ALS sweep](../benchmarks/rolling/als_sweep.json).

The post-selection comparison below uses the same 59,323 warm user-window targets in folds 5–9. The four fixed baselines come from the reference run; ItemKNN and ALS use configurations selected on folds 1–4. The validity limit described above applies to this table.

| Model | HR@20 | MRR@20 | NDCG@20 |
| :--- | ---: | ---: | ---: |
| Random | 0.000034 | 0.000004 | 0.000010 |
| Global Popularity | 0.007855 | 0.001671 | 0.002986 |
| Recent Popularity | 0.008209 | 0.002424 | 0.003693 |
| Category Popularity | 0.041518 | 0.011722 | 0.018217 |
| ItemKNN, selected lambda 100 | 0.041889 | 0.018687 | 0.023962 |
| ALS, selected 128 factors / 40 iterations / regularization 0.01 | 0.027291 | 0.009456 | 0.013385 |

Category Popularity leads ItemKNN on folds 5–7; ItemKNN leads on folds 8–9. Their pooled difference is only 0.000371 in HR@20 and should not be treated as a confident model win without paired uncertainty analysis. ALS trails both on this cohort. The five-fold comparison cannot restore blindness after the nine-fold reference results were viewed.

## Cold users

For 1,262,289 first-time users, Global Popularity gives HR@20 **0.011394** and Recent Popularity **0.011649**. About 88.69% of their target items are present in the corresponding training catalog. These are fallback results with no user history and must not be pooled with warm-personalized results. [Cold benchmark artifact](../benchmarks/rolling/cold.json).

## Reproduction and limits

Run `prepare_rolling_data.py`, `sweep_rolling.py --model item_knn`, `sweep_rolling.py --model als`, `benchmark_rolling.py`, and `benchmark_rolling_cold.py` with Python 3.13. See the [README](../README.md) for commands and data paths. The manifest records hashes of the processed interactions, both raw property CSVs, and all generated fold files; the result artifacts bind to that full manifest fingerprint. A fresh rebuild from the source files matched all 27 fold Parquet files byte for byte. Metrics use user-window weighting, so repeated users across folds contribute more than once. Earlier leave-last-out scores are excluded from these tables because they use a different evaluation task.
