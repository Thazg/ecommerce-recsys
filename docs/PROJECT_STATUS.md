# Project status

**Updated:** 2026-10-05

**Milestone:** M6 implemented and rolling M4–M6 evaluation complete; M7 has not started.

## Implementation

M0–M3 provide ingestion, interaction processing, split logic, and offline ranking metrics. M4 includes Random, Global Popularity, Recent Popularity, and Category Popularity. M5 includes ItemKNN. M6 includes educational MF/BPR and implicit ALS. There is no M7 candidate generator or online service yet.

The current repair fixes ItemKNN's tied self-neighbor defect and sparse similarity calculation, RandomRecommender's unknown/dense-history behavior, benchmark leakage checks, and cold-runner interruption/empty-fold handling. It introduces rolling global time cutoffs, train-time item/category catalogs, a single shared target cohort for M4–M6, and content fingerprints for raw properties and generated folds. The old 200,028-user leave-last-out results remain historical. The discarded 3,590-user single-cutoff benchmark has been removed.

## Current benchmark

The [rolling protocol](ROLLING_EVALUATION_PROTOCOL.md) has nine folds with 90,107 warm user-window targets from 71,982 distinct people. A separate 1,262,289 first-time users are measured as a cold cohort. Across the nine folds, 11.10% of warm targets are items absent from the corresponding training catalog, so no train-only recommender can retrieve them.

The nine-fold reference run on the same warm targets gives HR@20: Random 0.000044, Global Popularity 0.007558, Recent Popularity 0.008101, Category Popularity 0.041950, ItemKNN with historical lambda 100 at 0.045391, and ALS with historical 128 factors/20 iterations at 0.029887. **Diagnostic, configs transferred:** folds 5–9 were visible in this run before the rolling sweeps were locked. The post-selection comparison uses folds 5–9, but it is not a blind holdout. See the [report](ROLLING_BENCHMARK_REPORT.md) for the disclosure.

ItemKNN's eight-value shrinkage sweep selected lambda 100 on folds 1–4 (pooled HR@20 0.052138). On folds 5–9 it obtains HR@20 0.041889 over 59,323 user-window targets from 50,630 people. Category Popularity obtains 0.041518 on those same targets. The small difference does not yet establish a robust winner. ALS's eight-configuration sweep selected 128 factors, 40 iterations, and regularization 0.01 on folds 1–4 (HR@20 0.035440); it obtains HR@20 0.027291 on folds 5–9. Its selection advantage over 20 iterations on folds 1–4 was about one hit, and the extra fitting cost merits review before using it as an M7 candidate source.

For first-time users, Global Popularity achieves HR@20 0.011394 and Recent Popularity 0.011649 across all nine folds. These are separate cold-start fallback results, not entries in the warm model ranking.

## Validation and next step

The reference benchmark reran successfully after both sweeps completed and retained all 54 fold-model results. A detailed [repository audit](REPO_AUDIT_2026-10-05.md) verified all nine saved folds against the source data. A second rebuild from raw properties reproduced all 27 fold Parquet files byte for byte; the manifest and result artifacts now bind to those file hashes. The current worktree passed 132 tests in the `ecommerce-recsys` Python 3.13 Conda environment, Ruff lint and formatting checks, and `git diff --check`. The sandbox requires a test temporary-directory permission workaround; production code needs no such workaround. Use the post-selection findings for M7 candidate-source planning, while retaining the non-blind disclosure.

Detailed historical M4–M6 reports remain in [BASELINE_REPORT.md](BASELINE_REPORT.md), [MF_EXPERIMENT_REPORT.md](MF_EXPERIMENT_REPORT.md), and [history](history/). Their per-user leave-last-out metrics are not comparable with the rolling benchmark.
