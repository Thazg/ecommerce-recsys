# Project status

**Updated:** 2026-10-05

**Stage:** Offline evaluation through implicit ALS is complete. Candidate generation and online serving are planned.

## Implemented

| Area | Current implementation |
| :--- | :--- |
| Data | Retailrocket ingestion, interaction processing, train-time item and category catalogs |
| Evaluation | Nine rolling time folds, shared warm targets, separate cold-user cohort, causal checks, HR/MRR/NDCG and coverage |
| Models | Random, global/recent/category popularity, ItemKNN, implicit ALS, educational MF/BPR |
| Reproducibility | Fixed seeds, numerical thread control, resumable checkpoints, source and fold SHA-256 verification, CI |

The [architecture overview](ARCHITECTURE_CURRENT.md) describes the code paths. The [evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md) defines the cohorts and eligibility rules.

## Measured results

The rolling benchmark includes **90,107 warm user-window targets from 71,982 distinct users** across nine folds. A separate **1,262,289 first-time users** form the cold cohort. In the warm cohort, 11.10% of targets are absent from their fold's training catalog and cannot be retrieved by train-only models.

ItemKNN and ALS were selected on folds 1–4. Their configurations and the four fixed baselines were measured on the same **59,323 warm targets** in folds 5–9:

| Model | HR@20 | MRR@20 | NDCG@20 |
| :--- | ---: | ---: | ---: |
| Random | 0.000034 | 0.000004 | 0.000010 |
| Global Popularity | 0.007855 | 0.001671 | 0.002986 |
| Recent Popularity | 0.008209 | 0.002424 | 0.003693 |
| Category Popularity | 0.041518 | 0.011722 | 0.018217 |
| ItemKNN (shrinkage 100) | 0.041889 | 0.018687 | 0.023962 |
| Implicit ALS (128 factors, 40 iterations, regularization 0.01) | 0.027291 | 0.009456 | 0.013385 |

The ItemKNN–Category HR@20 gap is 0.000371, and their fold-level ordering changes. No robust winner is claimed. For first-time users, global and recent popularity achieve HR@20 of 0.011394 and 0.011649 respectively; those scores are not pooled with warm results.

**Validity limit:** Reference scores for folds 5–9 were inspected before the sweep configurations were locked. These are post-selection diagnostic results, not a blind holdout. See the [benchmark report](ROLLING_BENCHMARK_REPORT.md) and [result artifacts](../benchmarks/rolling/) for per-fold metrics, coverage, and latency.

## Next milestone

Candidate generation should measure Recall@N, candidate availability, serving cost, and fallback behavior on a shared temporal cohort. The current offline latency figures exclude training and API overhead. A new untouched time period is needed for independent model-selection confirmation.

The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier per-user leave-last-out experiments. Their metrics are retained for provenance but are not directly comparable with rolling results.
