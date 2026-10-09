# Project status

**Updated:** 2026-10-09

**Stage:** M8 Two-Tower v1 sweep, selection lock and folds 5–9 diagnostics are
complete. The implementation aligns inference history with training and clears
stale state on refit. Prior exploratory Two-Tower metrics are excluded. ALS v2
sweep and diagnostic results are reused as the unchanged comparator and are
hash-bound into the M8 v1 selection lock. Configurations were selected on folds
1–4; folds 5–9 are post-selection diagnostics, not blind validation. The
project remains offline; online serving is not implemented.

## Implemented

| Area | Current implementation |
| :--- | :--- |
| Data | Retailrocket ingestion, interaction processing, train-time item and category catalogs |
| Evaluation | Nine rolling time folds, shared warm targets, separate cold-user cohort, causal checks, HR/MRR/NDCG and coverage |
| Models | Random, global/recent/category popularity, ItemKNN, implicit ALS, educational MF/BPR |
| Retrieval | Common candidate interface, exact ALS, ItemKNN, category and popularity sources, source-aware reciprocal-rank fusion |
| M8 retrieval | Deterministic CPU two-tower retriever with shared history encoding, train-only category features, sampled-softmax training and exact catalog scoring |
| Reproducibility | Fixed seeds, numerical thread control, resumable checkpoints, source and fold SHA-256 verification, CI |

The [architecture overview](ARCHITECTURE_CURRENT.md) describes the code paths. The [evaluation protocol](ROLLING_EVALUATION_PROTOCOL.md) defines the cohorts and eligibility rules.

## Recommendation results

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

## Candidate retrieval results

The M7 artifact contains **126 comparisons**: nine folds, two cohorts and seven
generators. The following candidate-recall figures use the same 59,323 warm
targets in folds 5–9. They retain the post-selection diagnostic validity limit.

| Generator | Recall@100 | Recall@500 | Recall@1000 |
| :--- | ---: | ---: | ---: |
| Exact ALS | 0.050705 | 0.087116 | 0.109216 |
| Hybrid without ALS | 0.081183 | 0.165180 | 0.213206 |
| Hybrid | 0.079750 | 0.163832 | 0.211537 |

Adding ALS changes pooled hybrid Recall@1000 by **-0.167 percentage points**.
This is a net ablation difference, not a statistical significance claim. The
[retrieval report](CANDIDATE_RETRIEVAL_REPORT.md) details all source results,
empty/full pool rates, cold retrieval, source contributions and cost. Regression
and artifact validation are documented with reproduction commands in that report.

## M8 two-tower results

The corrected Two-Tower v1 configuration (dimension 128, history 50) was
selected on folds 1–4. On folds 5–9 it achieved pooled Recall@100/500/1000 of
0.044485 / 0.096185 / 0.127640 over 59,323 warm user-windows. The same-window
ALS v2 comparator achieved 0.050705 / 0.087116 / 0.109216. These folds had been
inspected before configuration lock, so the results are post-selection
diagnostics, not blind validation or evidence of statistical significance.
The [two-tower report](TWO_TOWER_REPORT.md) includes per-fold results, cost,
latency scope, artifact hashes and reproduction commands.

## Next milestone

M8 v1 is complete. Any follow-up milestone must preserve the shared rolling
targets and train-time catalogs and report its trade-off against exact ALS and
Two-Tower retrieval. Folds 5–9 remain non-blind diagnostics; independent model
selection requires a later untouched time period. The [roadmap](ROADMAP.md)
defines later milestone gates.

The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier per-user leave-last-out experiments. Their metrics are retained for provenance but are not directly comparable with rolling results.
