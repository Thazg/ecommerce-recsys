# Offline recommendation policy benchmark

**State:** Development selection and all five later-fold diagnostics are complete.
**Verified:** 2026-10-15. The warm/cold routes remain fixed by the development lock.

## Purpose and comparison scope

This benchmark compares complete fixed recommendation policies from candidate
generation through Top-20 ordering. It identifies an offline reference for
artifact packaging using development scores, with separate routes for returning
users and first-time users. The candidate grid contains the supported direct
sources, reciprocal-rank fusion with and without ALS, learned ordering and the
locked category-novelty option. Two-Tower remains a separate retrieval experiment;
the failed ANN and sequential settings are outside this adopted-policy grid.
Each included policy covers candidate generation through final Top-20 output.
The grid uses sources compatible with the published ranker feature schema.
Adding Two-Tower to that learned hybrid would require new source-evidence
features and ranker training; the educational MF/BPR models are not candidate
sources. The grid is finite and does not claim to exhaust every model in the
repository.

All policies use the same fold cutoff, item/category snapshot, target cohort and
Top-5/10/20 output budgets. Each generator is asked for up to 1,000 eligible,
unseen candidates. The five direct sources preserve their direct-source semantics;
category, ItemKNN and ALS can return empty lists rather than implicit popularity
backfill. These direct-source rows therefore differ from the standalone
recommenders in the rolling Top-K report. Popularity is explicitly attributed
inside hybrid pools and in the separate cold route.

## Fixed models and selection

The original retrieval settings, pairwise ranker alpha 0.01, source-evidence
feature transforms and category bonus 0.10 remain fixed. ItemKNN uses shrinkage
100; implicit ALS uses 128 factors, 40 iterations, regularization 0.01 and seed
42 from the locked [ItemKNN](../benchmarks/rolling/item_knn_sweep.json) and
[ALS](../benchmarks/rolling/als_sweep.json) sweeps. Recent popularity uses a
30-day window at the declared cutoff. Fusion uses RRF constant 60 and source
depth 1,000. Development scores use
fold 1 ranker training for fold 2, folds 1–2 for fold 3, and folds 1–3 for fold
4. Every training label window ends by the scoring fold's cutoff. The final
diagnostic ranker is the published model fit on labelled folds 1–4.

Two no-ALS learned rows apply those same full-hybrid-trained weights and RMS
scales to their own no-ALS candidate lists. ALS evidence is absent in their
features. This is a model transfer comparison with changed candidate and feature
distributions; no ranker was retrained on a no-ALS pool. RRF and the learned
variants within each hybrid use that hybrid's exact same candidates.

Choose warm and cold routes independently on pooled development folds 2–4:
more hits@20, then larger NDCG@20 numerator, then fewer source models, then
smaller category bonus, then policy name. The rule was fixed before this
benchmark's development scoring. Accuracy selects the reference; diversity,
availability and cost qualify the choice and are not additional tuning gates.
The complete development artifact is hashed into a selection lock before the
diagnostic phase can run.

The completed development comparison selected **full-hybrid learned ordering**
for warm requests, with **1,631/25,438 hits@20** (HR@20 **0.064117**), and
**recent popularity** for cold requests, with **4,557/405,518 hits@20**
(HR@20 **0.011237**). Both routes were locked before this benchmark scored
folds 5–9. Category novelty remains an optional measured trade-off rather than
part of the accuracy-selected warm route. The no-ALS learned transfer found
1,507 development hits@20; its lower fitting cost did not override the
predeclared accuracy-first rule.
The lock stores these route identifiers as `hybrid_learned` and
`recent_popularity`.

The development period contains 25,438 warm and 405,518 cold user-windows.
Retrieval settings, ranker alpha and category bonus already used these periods,
so the full-policy selection reuses development data and can be optimistic.
Folds 5–9 contain 59,323 warm and 715,331 cold user-windows. Earlier experiments
inspected those periods; their later results are post-selection diagnostics,
not blind validation. The selected routes cannot change using those scores.

## Development evidence

The [development artifact](../benchmarks/model_policy/development_v1.json)
and [selection lock](../benchmarks/model_policy/selection_lock_v1.json)
contain all 42 comparisons across three folds: eleven warm and three cold
policies per fold. The warm table uses 25,438 requests; the cold table uses
405,518 requests. All rates retain unreachable targets in their denominators.

### Warm

| Policy | Hits@20 | HR@5 | HR@10 | HR@20 | MRR@20 | NDCG@20 | Candidate Recall@1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Global popularity | 171 | 0.002123 | 0.003617 | 0.006722 | 0.001144 | 0.002336 | 0.104371 |
| Recent popularity | 199 | 0.002162 | 0.003813 | 0.007823 | 0.001347 | 0.002712 | 0.105236 |
| Category direct | 1,106 | 0.019027 | 0.029130 | 0.043478 | 0.012361 | 0.019120 | 0.135506 |
| ItemKNN direct | 1,276 | 0.033768 | 0.042417 | 0.050161 | 0.022392 | 0.028708 | 0.060186 |
| Exact ALS direct | 854 | 0.016707 | 0.023901 | 0.033572 | 0.010691 | 0.015733 | 0.129963 |
| Full hybrid RRF | 1,019 | 0.021189 | 0.029405 | 0.040058 | 0.013997 | 0.019737 | 0.217824 |
| No-ALS RRF | 780 | 0.015213 | 0.021149 | 0.030663 | 0.010428 | 0.014830 | 0.215386 |
| Full hybrid learned (locked) | 1,631 | 0.031803 | 0.045798 | 0.064117 | 0.021142 | 0.030557 | 0.217824 |
| Full hybrid learned + category | 1,625 | 0.030702 | 0.045169 | 0.063881 | 0.020401 | 0.029905 | 0.217824 |
| No-ALS learned transfer | 1,507 | 0.028383 | 0.043164 | 0.059242 | 0.018960 | 0.027799 | 0.215386 |
| No-ALS learned + category transfer | 1,503 | 0.027911 | 0.042535 | 0.059085 | 0.018599 | 0.027460 | 0.215386 |

### Cold

| Policy | Hits@20 | HR@5 | HR@10 | HR@20 | MRR@20 | NDCG@20 | Candidate Recall@1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Global popularity | 4,343 | 0.003704 | 0.006769 | 0.010710 | 0.001968 | 0.003860 | 0.123378 |
| Recent popularity | 4,557 | 0.003817 | 0.006700 | 0.011237 | 0.002131 | 0.004090 | 0.123750 |
| Popularity RRF | 4,421 | 0.003817 | 0.006944 | 0.010902 | 0.002106 | 0.004010 | 0.123662 |

ItemKNN has more development hits@5 than the selected warm policy (859 versus
809). The lock prioritizes Top-20 accuracy and does not select a winner at every
output budget. Lower-cost no-ALS transfer and category variety remain explicit
trade-offs, rather than post-hoc reasons to change the locked route.

## Quality, availability and diversity

Keep every cohort target in the primary HR/MRR/NDCG denominator, including
catalog-unreachable targets and targets missing from the pool. Report target
availability at 1,000 candidates separately from final ranking quality. HR@K
equals Recall@K because each request has one target. Reachable candidate recall
uses only targets in the cutoff catalog and is explicitly conditional.

Known-category item slots and distinct-known-category slots use 20 times the
request count, including empty output positions. Unknown categories add zero.
Item coverage divides unique Top-20 items by the fold's own train catalog;
it is reported per fold and is not pooled across changing catalogs. The
category utility changes learned rank with a distinct-category bonus, without
item-distance or aspect-probability modeling.

Cold quality uses the entire first-time-user cohort. Since each cold policy
receives the same empty context, exact target-item frequency aggregation gives
the same integer hit and request counts as evaluating its shared output for
every cold user. Cold and warm rates are never pooled together.

## Post-selection diagnostic evidence

The complete [diagnostic artifact](../benchmarks/model_policy/diagnostic_v1.json)
contains all 70 later-fold comparisons. Together with development, the benchmark
contains **112 policy/fold/cohort comparisons**. The following warm rates use
**59,323 user-windows**; cold rates use **715,331 first-time-user targets**.
Reachable counts are 54,412 warm and 663,319 cold. All targets remain in the
primary denominator, including those outside the cutoff catalog.

### Warm

| Policy | Hits@20 | HR@5 | HR@10 | HR@20 | MRR@20 | NDCG@20 | Candidate Recall@1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Global popularity | 466 | 0.002680 | 0.004181 | 0.007855 | 0.001671 | 0.002986 | 0.098158 |
| Recent popularity | 487 | 0.003978 | 0.006068 | 0.008209 | 0.002424 | 0.003693 | 0.108457 |
| Category direct | 2,571 | 0.018863 | 0.029736 | 0.043339 | 0.012089 | 0.018899 | 0.167203 |
| ItemKNN direct | 2,452 | 0.027949 | 0.034911 | 0.041333 | 0.018549 | 0.023730 | 0.050099 |
| Exact ALS direct | 1,619 | 0.014025 | 0.020313 | 0.027291 | 0.009456 | 0.013385 | 0.109216 |
| Full hybrid RRF | 2,285 | 0.019402 | 0.027932 | 0.038518 | 0.012984 | 0.018597 | 0.211537 |
| No-ALS RRF | 1,967 | 0.017481 | 0.024426 | 0.033157 | 0.011482 | 0.016252 | 0.213206 |
| Full hybrid learned (locked) | 3,237 | 0.027797 | 0.040018 | 0.054566 | 0.018427 | 0.026383 | 0.211537 |
| Full hybrid learned + category | 3,236 | 0.027612 | 0.040204 | 0.054549 | 0.018118 | 0.026135 | 0.211537 |
| No-ALS learned transfer | 3,120 | 0.026027 | 0.038434 | 0.052593 | 0.017110 | 0.024911 | 0.213206 |
| No-ALS learned + category transfer | 3,119 | 0.025858 | 0.038670 | 0.052577 | 0.016894 | 0.024738 | 0.213206 |

### Cold

| Policy | Hits@20 | HR@5 | HR@10 | HR@20 | MRR@20 | NDCG@20 | Candidate Recall@1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Global popularity | 8,308 | 0.005158 | 0.007462 | 0.011614 | 0.003115 | 0.004958 | 0.116206 |
| Recent popularity | 8,416 | 0.005843 | 0.008177 | 0.011765 | 0.004301 | 0.005904 | 0.122012 |
| Popularity RRF | 8,945 | 0.004982 | 0.007886 | 0.012505 | 0.003999 | 0.005818 | 0.119838 |

The locked warm route has **3,237 hits@20**, versus **3,120** for the no-ALS
learned transfer: a difference of **117/59,323**, or **0.001972** absolute HR.
Full learned ordering has more hits@20 in each later fold. The no-ALS pool
contains 99 more targets at 1,000 candidates (12,648 versus 12,549), yet its
transferred order places fewer in Top-20. This comparison changes both pool
and evidence distribution while preserving full-pool-trained weights; it does
not estimate an isolated ALS benefit or the quality of a retrained no-ALS model.

ItemKNN direct has nine more hits@5 than the locked warm route (1,658 versus
1,649), while its Top-20 hit count is lower (2,452 versus 3,237). Its MRR@20
is also slightly higher. The selected route wins the declared Top-20 target
metric within this grid, without dominating every metric or cost.

The locked cold route has **8,416 hits@20** (HR@20 **0.011765**). Popularity
RRF has **8,945** (HR@20 **0.012505**), a later-fold advantage of **529 hits**
or **0.000740** absolute HR. Recent popularity has higher NDCG@20 than RRF
in this diagnostic. Development selected recent (4,557 versus 4,421 hits@20),
so the diagnostic does not replace the cold route. These already-inspected
periods disclose a limitation of the reference decision; they cannot supply a
new blind model-selection claim.

All five source pool totals reconcile with the candidate benchmark. Full RRF,
learned ordering and the category option reproduce the published ranking and
re-ranking metrics. Direct Global/Recent Top-5/10/20 rates also match the
rolling warm/cold artifacts within their six-decimal rounding. These are
accounting and implementation checks, without a significance claim.

## Warm availability and category slots

| Policy | Mean pool | Empty output | Short output | Known category slots@20 | Distinct category slots@20 |
| --- | --- | --- | --- | --- | --- |
| Global popularity | 1000.00 | 0.000000 | 0.000000 | 0.999984 | 0.832282 |
| Recent popularity | 1000.00 | 0.000000 | 0.000000 | 0.982574 | 0.758675 |
| Category direct | 572.59 | 0.075316 | 0.086442 | 0.919522 | 0.069722 |
| ItemKNN direct | 40.07 | 0.146132 | 0.325338 | 0.652868 | 0.331409 |
| Exact ALS direct | 1000.00 | 0.000000 | 0.000000 | 0.976183 | 0.566291 |
| Full hybrid RRF | 1000.00 | 0.000000 | 0.000000 | 0.986579 | 0.667369 |
| No-ALS RRF | 1000.00 | 0.000000 | 0.000000 | 0.994779 | 0.759120 |
| Full hybrid learned (locked) | 1000.00 | 0.000000 | 0.000000 | 0.958418 | 0.125625 |
| Full hybrid learned + category | 1000.00 | 0.000000 | 0.000000 | 0.962514 | 0.146108 |
| No-ALS learned transfer | 1000.00 | 0.000000 | 0.000000 | 0.934392 | 0.103800 |
| No-ALS learned + category transfer | 1000.00 | 0.000000 | 0.000000 | 0.940501 | 0.123418 |

## Per-fold route quality

### Warm route quality

| Fold | Warm requests | Full learned hits@20 | No-ALS transfer hits@20 | Full NDCG@20 | No-ALS NDCG@20 | Full coverage@20 | No-ALS coverage@20 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 10,349 | 636 | 610 | 0.029654 | 0.027969 | 0.167281 | 0.169051 |
| 6 | 10,720 | 603 | 581 | 0.026903 | 0.024948 | 0.157150 | 0.159490 |
| 7 | 11,950 | 654 | 631 | 0.026696 | 0.025121 | 0.163049 | 0.165337 |
| 8 | 12,765 | 675 | 652 | 0.025023 | 0.023591 | 0.152257 | 0.154314 |
| 9 | 13,539 | 669 | 646 | 0.024478 | 0.023603 | 0.152643 | 0.154436 |

### Cold route quality

| Fold | Cold requests | Global hits@20 | Recent hits@20 (locked) | RRF hits@20 | Recent HR@20 | RRF HR@20 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 147,821 | 1,799 | 1,651 | 1,796 | 0.011169 | 0.012150 |
| 6 | 138,959 | 1,231 | 1,420 | 1,362 | 0.010219 | 0.009801 |
| 7 | 144,861 | 1,406 | 1,494 | 1,631 | 0.010313 | 0.011259 |
| 8 | 141,666 | 1,954 | 1,984 | 1,979 | 0.014005 | 0.013969 |
| 9 | 142,024 | 1,918 | 1,867 | 2,177 | 0.013146 | 0.015328 |

## Matched inference cost

The benchmark times independent complete policy calls on 100 deterministically
sampled warm users per fold, repeated three times. Samples sort by SHA-256 of
fold/user identity; a fixed rotated policy order reduces persistent order bias.
Each policy has one excluded warmup. Each measured call performs retrieval,
fusion when applicable, feature-row construction, transforms and learned
scoring when applicable, Top-20 ordering/re-ranking and contract validation.
Its output must match that request's quality-pass output exactly. The shared
source calls used during full-cohort quality accounting are not used to estimate
these inference latencies. Percentiles use linear interpolation.

Contexts, fitted models and feature aggregates already exist. Timing excludes
loading data, preparing history/context, snapshot/model fitting, persistence,
networking, cache/service middleware and an HTTP API. These are local warmed
offline inference calls; they do not establish serving latency or an SLA.
Direct sources also request the fixed 1,000-candidate budget in this benchmark;
an optimized direct Top-20 implementation could have a different cost.

Cold latency repeats each policy's identical empty-context call 100 times per
fold. This shared-context workload is separate from warm sampled-user timing
and cannot be compared as if it measured personalized requests. Accuracy still
covers every cold target.

Source fit times, feature-snapshot preparation and development ranker training
are recorded separately. The runner fits all five sources in one shared process.
Summed source-fit estimates attribute only a policy's constituents; they are
not separately measured isolated training jobs. ALS bytes refer only to factor
arrays and exclude sparse matrices, Python objects and whole-process memory.

### Measured cost evidence

The run used an Intel Core i7-10750H on Windows 10, Python 3.13.15,
NumPy 2.5.2, SciPy 1.18.1 and implicit 0.7.3, with one numerical worker.
Each warm policy has 300 measured calls per fold; each cold policy has 100.
The following ranges are minima/maxima of five fold-level statistics, rather
than percentiles pooled across folds. Complete per-policy/fold timings are in
the diagnostic artifact.

| Policy | Per-fold p50 ms range | Per-fold p95 ms range | Source-fit estimate s range |
| --- | --- | --- | --- |
| Global popularity | 2.84–3.93 | 3.54–5.56 | 0.88–1.22 |
| Recent popularity | 2.78–3.84 | 3.67–6.51 | 0.46–0.80 |
| Category direct | 1.40–2.42 | 3.87–5.34 | 1.01–1.68 |
| ItemKNN direct | 1.98–3.49 | 3.79–5.95 | 31.67–112.40 |
| Exact ALS direct | 11.30–15.90 | 15.18–22.64 | 267.16–516.97 |
| Full hybrid RRF | 27.87–36.60 | 49.36–251.37 | 301.88–632.22 |
| No-ALS RRF | 14.41–19.64 | 21.74–33.36 | 34.71–115.25 |
| Full hybrid learned (locked) | 65.40–88.28 | 89.23–129.13 | 301.88–632.22 |
| Full hybrid learned + category | 65.98–88.76 | 79.09–291.82 | 301.88–632.22 |
| No-ALS learned transfer | 51.43–70.51 | 62.56–105.67 | 34.71–115.25 |
| No-ALS learned + category transfer | 51.45–69.55 | 63.72–144.07 | 34.71–115.25 |

### Per-fold warm route cost

| Fold | Full learned p50 ms | Full learned p95 ms | No-ALS transfer p95 ms | Full sources fit s | No-ALS sources fit s | Feature snapshot s | ALS factors MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 67.03 | 127.74 | 81.04 | 301.88 | 34.71 | 4.97 | 423.01 |
| 6 | 65.46 | 112.97 | 68.98 | 345.42 | 44.76 | 6.38 | 502.44 |
| 7 | 67.67 | 89.23 | 65.75 | 421.80 | 56.57 | 7.08 | 576.18 |
| 8 | 88.28 | 129.13 | 105.67 | 487.23 | 72.77 | 8.83 | 652.74 |
| 9 | 65.40 | 93.43 | 62.56 | 632.22 | 115.25 | 13.17 | 727.42 |

### Per-fold cold shared-context cost

| Fold | Global p95 ms | Recent p95 ms (locked) | RRF p95 ms | Recent source-fit estimate s |
| --- | --- | --- | --- | --- |
| 5 | 4.60 | 3.87 | 18.76 | 0.80 |
| 6 | 3.40 | 3.40 | 11.14 | 0.66 |
| 7 | 4.11 | 3.49 | 11.63 | 0.64 |
| 8 | 7.52 | 7.40 | 25.23 | 0.73 |
| 9 | 3.09 | 3.10 | 11.36 | 0.46 |

Cold source-fit estimates use the same shared source-fit records; they do not
measure isolated cold training jobs.

Full-source fit estimates range from **301.88–632.22 seconds per fold**;
no-ALS source estimates range from **34.71–115.25 seconds**. The selected
route retains that ALS cost under its accuracy-first rule. ALS factor arrays
range from **423.01–727.42 MiB**; this excludes sparse matrices, feature
aggregates and other process allocations.

Tail timings vary substantially, including full RRF p95 up to 251.37 ms and
the category option up to 291.82 ms. This single local run has no timing
uncertainty estimate or idle-host guarantee. The paired workload supports a
descriptive cost comparison; those tails do not establish a stable architecture
ranking or a serving SLA.

## Provenance and reproduction

The development identity pins the published final-ranker and re-ranking
diagnostic files by SHA without using their scores for route selection. The
runner verifies the rolling input/fold hashes and the published candidate,
ranking-data, ranker and category-lock chains. The original ranking source
revision must exist locally; all historical dependency files must still match
that revision. The new fingerprint binds this runner, its accounting code and
the verified historical re-ranking dependency chain, so unrelated future
package modules do not invalidate it. That transitive scope includes
`scripts/learned_ranker.py`, `scripts/benchmark_ranker.py` and
`scripts/benchmark_candidates.py`; changed tracked historical source is also
rejected before reuse. The current-package ranker hash includes later modules,
so it is replaced by the verified historical file scope rather than omitted.
Frozen upstream JSON is not rewritten. Git attributes preserve exact JSON
serialization, including explicit CRLF rules for legacy checksum inputs.
Changing those bytes invalidates the chain even if parsed values are unchanged.

Every completed fold is an atomic checkpoint. Resume rejects a changed policy,
runtime, code or input identity, invalid count/rate bounds, a missing comparison,
wrong chronology, modified pooled values or a diagnostic model differing from
the frozen ranker. Incomplete diagnostic checkpoints retain `complete: false`.
The result SHA identifies quality/model content independently of measured timing;
the full payload checksum also protects cost and timing fields.

The [provenance supplement](../benchmarks/model_policy/provenance_v1.json)
records both seeds as explicit integer fields and directly binds the independent
ranking feature audit. `scripts/verify_model_policy.py` extracts the ALS seed
from the already fingerprinted source and checks the ranker's sampling seed
against its published development policy. It verifies the audit's quality SHA,
verifier SHA, complete fold coverage, file hashes, counts and zero null/nonfinite
findings against the same hash-verified Parquet inputs. It records source file
hashes and all three completed policy artifact hashes, then refuses replacement
if those inputs change.

This is a retrospective verification supplement, recorded after the completed
diagnostic. It documents existing code-bound settings and audit evidence; it
does not claim that these explicit fields were in the original pre-diagnostic
lock. The original development, lock and diagnostic JSON bytes remain intact.
The supplement is evaluation provenance, without serialized serving models or
a model-bundle loading contract.

```sh
python scripts/benchmark_model_policy.py development
python scripts/benchmark_model_policy.py lock
python scripts/benchmark_model_policy.py diagnostic
python scripts/verify_model_policy.py
pytest
ruff check .
ruff format --check .
```

Run from the repository root with the Python 3.13 ecommerce-recsys environment
and verified upstream ranking Parquet available. The reproduction steps for
those frozen inputs are in the ranking dataset and learned-ranking reports.
The historical guard pins every package file present at the ranking source
revision, including educational recommenders outside the selected route.
Use a compatible full-history checkout, such as
`30e685babbdeec682084830f23834a6141a18f9a`, for the completed provenance check.
Later educational fit-lifecycle changes correctly make this guard reject the
current tree. They do not revise the frozen policy results; do not substitute
new SHA fields or weaken the historical guard.
Use the [README reproduction guide](../README.md#reproduce) for the recorded
historical source checkout, byte-preserved JSON and scratch checkpoint steps.

## Limits of the reference decision

This finite policy grid cannot establish the best retriever, ranker or business
objective. Its selection prioritizes Top-20 target accuracy; it does not impose
per-fold or Top-5/10 relevance gates, a category-variety requirement, or a latency
budget. Repeated users can appear in several windows. The no-ALS model transfer
does not replace a prospective pool-specific training experiment. Sparse
category metadata limits the diversity interpretation. The measured machine,
thread setting and warmed workload limit cost generalization. Independent model
confirmation needs a later untouched period, and online behavior requires the
following artifact/service milestones and operational measurements.

Pooled quality weights each user-window equally, so larger folds contribute
more targets. Catalog coverage remains available per fold; it is omitted from
the pooled record because catalogs change between windows. The benchmark has
no activity or item head/tail slice analysis and no paired uncertainty interval.
Its aggregate route ordering does not establish benefit for every user/item
segment or quantify the stability of the cold development margin.

### Selection under an operating budget

The present lock optimizes accuracy on development data. A prospective
cost-constrained experiment would first declare latency, fitting and memory
limits, a maximum acceptable absolute HR loss against a reference, and any
availability or category-variety constraints. Among feasible policies within
that relevance tolerance, it could select the lowest declared cost. The
workload, uncertainty rule and activity/head-tail slice gates would also be
fixed before scoring. A pool-specific no-ALS ranker would avoid the transfer
confound in the current ablation. Selection would use prospective development
data followed by a lock and a later untouched evaluation period.

Those constraints cannot be retrofitted to choose a preferred result from the
already-inspected folds 5–9. A request to save substantial cost for a small
relevance loss therefore needs an explicit operating objective and a new
experiment; the current accuracy-first lock is an offline reference for that
discussion. Versioned model packaging, artifact loaders and API behavior belong
to the artifact/service stages of the [roadmap](ROADMAP.md).
The subsequent [artifact contract](MODEL_ARTIFACTS.md) packages this unchanged
reference as a cutoff snapshot and defines its independent Python loader.
