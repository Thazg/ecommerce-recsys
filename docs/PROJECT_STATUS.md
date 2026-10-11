# Project status

**Updated:** 2026-10-11

**Stage:** M11 has trained and evaluated an offline pairwise ranker on the
fixed full-hybrid candidate pool. M9 ended with an ANN no-go; no ANN index was
adopted. The project remains offline; no production ranker or online serving
is implemented. Folds 5–9 were inspected in earlier milestones and remain
post-selection diagnostics, not blind validation.

## Implemented

| Area | Current implementation |
| :--- | :--- |
| Data | Retailrocket ingestion, interaction processing, train-time item and category catalogs |
| Evaluation | Nine rolling time folds, shared warm targets, separate cold-user cohort, causal checks, HR/MRR/NDCG and coverage |
| Models | Random, global/recent/category popularity, ItemKNN, implicit ALS, educational MF/BPR |
| Retrieval | Common candidate interface, exact ALS, ItemKNN, category and popularity sources, source-aware reciprocal-rank fusion |
| M8 retrieval | Deterministic CPU two-tower retriever with shared history encoding, train-only category features, sampled-softmax training and exact catalog scoring |
| M9 feasibility | Reproducible exact-cost profile and paired fold-1 ANN pilot; no ANN source promoted to the package after the speed gate failed |
| M10 ranking data | Causal warm request/candidate Parquet for folds 1–4, as-of features, zero-positive request audit, SHA-bound checkpoints and independent file verification |
| M11 learned ranking | Deterministic pairwise linear ranker, chronological development selection, SHA-bound lock and same-pool RRF comparison on folds 5–9 |
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

## M9 ANN feasibility result

The M9 exact-cost profile measured selected Two-Tower retrieval on 1,000 sampled
warm requests per development fold, repeated three times. Exact p95 at budget
1,000 was 8.426, 13.806, 12.083 and 13.550 ms on folds 1–4. Since three folds
crossed the declared 10 ms cost trigger, a Faiss HNSW pilot compared four index
settings with paired exact calls on fold 1. All four ANN p95 values were slower
than exact (ANN 14.844–35.411 ms; paired exact 9.311–10.698 ms). Each failed the
gate requiring ANN p95 at most half of exact on every development fold. M9
stopped at that point: no full ANN quality sweep, folds 5–9 ANN diagnostic or
serving claim exists. The [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) provides sample
hit counts, index costs, compatibility limits and the no-go decision.

## M10 ranking dataset

M10 regenerated the fixed M7 full-hybrid pool for **30,784 warm user-windows**
on development folds 1–4. It produced 30,784,000 candidate rows, including
6,717 positive rows, for pooled Candidate Recall@1000 of **0.218198** with all
warm targets in the denominator. The 5,087 targets outside their fold's
train-time catalog and 18,980 catalog-reachable targets missed by retrieval
remain in the request audit. All four folds reproduced M7's hit and pool-count
totals; an independent Parquet scan found no null or nonfinite values. The
[ranking dataset report](RANKING_DATASET_REPORT.md) explains the feature schema,
provenance, build cost and limits. These are retrieval-data measurements, not
learned-ranker Top-K results.
The ItemKNN/ALS configurations and full-hybrid candidate policy were selected
using folds 1–4. M10's fold 1–4 recall is therefore an in-sample dataset
construction diagnostic, not an independent retrieval-quality estimate.

## M11 learned ranking

M11 trained on labelled warm folds 1–4 and selected `alpha=0.01` from a fixed
three-setting grid using pooled development HR@20. On the same regenerated
full-hybrid pools for **59,323 warm user-windows** in folds 5–9, RRF ranked
**2,285** targets in the Top-20 (HR@20 **0.038518**); the locked ranker ranked
**3,237** (HR@20 **0.054566**). The difference is **952 hits** or **0.016048**
in HR. Both orders share Candidate Recall@1000 of **0.211537**
(12,549/59,323 targets in pool). All five folds had a positive hit difference.
These are post-selection diagnostics, not blind validation or a significance
claim. The [learned-ranking report](LEARNED_RANKING_REPORT.md) gives per-fold
HR/MRR/NDCG, model policy, cost scope, artifact provenance and limitations.

## Next milestone

The [roadmap](ROADMAP.md) defines optional sequential modelling and later
re-ranking, model-policy and serving gates. Independent confirmation of M11
requires a later untouched time period; its present results should not be used
as a production model-selection claim.

The [baseline](BASELINE_REPORT.md) and [MF](MF_EXPERIMENT_REPORT.md) reports document earlier per-user leave-last-out experiments. Their metrics are retained for provenance but are not directly comparable with rolling results.
