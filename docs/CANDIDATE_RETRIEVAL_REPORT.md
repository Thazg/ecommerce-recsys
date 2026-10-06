# Candidate retrieval benchmark report

**Milestone:** M7

**Metric units:** Accuracy, coverage and pool rates are fractions in `[0, 1]`. See [metrics and protocols](METRICS_AND_PROTOCOLS.md) for configurations, fallback semantics and timing scopes.

## Scope and protocol

This report evaluates candidate retrieval independently of a learned final ranker. Five direct sources and two fixed hybrid policies are measured on the existing nine rolling snapshots. The full benchmark contains 90,107 warm user-window targets and 1,262,289 first-time targets, with 126 complete fold/cohort/generator rows.

ItemKNN uses 20 neighbors, a minimum of five interactions and shrinkage 100. ALS uses 128 factors, 40 iterations, regularization 0.01 and seed 42. These configurations come from the completed M5–M6 sweeps. Each source is asked for up to 1,000 candidates; the configured budget does not guarantee a full pool. On warm folds 5–9, ItemKNN returned a mean of 40.07 candidates and was empty for 14.61% of requests. Both hybrids use equal-weight reciprocal rank fusion with constant 60; the ablation removes ALS. No M7 sweep or final-fold tuning is performed.

Source ranks refer to the eligible, seen-filtered source list. Fusion preserves those supplied ranks when filtering cached entries. Popularity fallback is attributed to explicit sources; direct personalized-source empty rates measure availability before hybrid fallback.

The inherited configurations were selected by HR@20 and are fixed references, not configurations optimized for Candidate Recall@1000.

**Validity:** Folds 1–4 are development diagnostics. Folds 5–9 below are exploratory post-selection diagnostics because these periods were previously inspected during M4–M6. They are not an independent blind holdout.

The first unseen target and train-time catalog are identical across generators. Seen products and products outside the cutoff catalog are filtered. A user ID may contribute targets in multiple windows. With one target per user-window, Candidate Recall@N equals the fraction whose target appears within that pool; it does not establish final Top-20 ranking quality.

## Warm retrieval: folds 5–9

Primary denominator: **59,323 user-window targets**. Of these, **54,412** have a target in the training-time catalog. Unreachable targets remain in the primary denominator.

| Generator | Recall@100 | Recall@500 | Recall@1000 | Reachable recall@1000 |
| :--- | ---: | ---: | ---: | ---: |
| ItemKNN | 0.048463 | 0.049997 | 0.050099 | 0.054620 |
| Exact ALS | 0.050705 | 0.087116 | 0.109216 | 0.119073 |
| Category | 0.093707 | 0.150532 | 0.167203 | 0.182294 |
| Recent popularity | 0.025589 | 0.071338 | 0.108457 | 0.118246 |
| Global popularity | 0.024206 | 0.063854 | 0.098158 | 0.107017 |
| Hybrid | 0.079750 | 0.163832 | 0.211537 | 0.230629 |
| Hybrid without ALS | 0.081183 | 0.165180 | 0.213206 | 0.232449 |

Category has the highest observed Recall@100 among these fixed policies; the hybrid without ALS has the highest observed Recall@1000. The ordering depends on candidate budget and does not establish a production winner.

## Availability and warm retrieval cost

The figures below use a requested pool of 1,000. Candidate counts and empty/full rates are pooled by user-window count. Latency is shown as the range of per-fold p95 values; percentiles are not averaged or presented as a pooled p95.

| Generator | Mean candidates | Empty pool rate | Full pool rate | Fold p95 range (ms) |
| :--- | ---: | ---: | ---: | ---: |
| ItemKNN | 40.07 | 0.146132 | 0.003405 | 3.52–5.03 |
| Exact ALS | 1000.00 | 0.000000 | 1.000000 | 15.05–17.43 |
| Category | 572.59 | 0.075316 | 0.334727 | 3.96–4.24 |
| Recent popularity | 1000.00 | 0.000000 | 1.000000 | 4.18–4.53 |
| Global popularity | 1000.00 | 0.000000 | 1.000000 | 4.37–4.70 |
| Hybrid | 1000.00 | 0.000000 | 1.000000 | 54.67–71.20 |
| Hybrid without ALS | 1000.00 | 0.000000 | 1.000000 | 22.87–26.61 |

Source latency includes retrieval, filtering and candidate records. Hybrid latency includes all constituent source calls plus fusion. Evaluation reuses shared source outputs and sums their measured costs for each hybrid. Timings exclude fitting, input loading, final ranking, network and API overhead. They are local offline CPU measurements with one numerical worker, not a serving SLA.

Linear percentiles use a shared helper. Top-20 recommendation timings and repeated cold-context timings have different workloads and must not be compared directly with these warm retrieval figures. See the [timing scope table](METRICS_AND_PROTOCOLS.md#timing-scopes).

## ALS ablation

The following differences are full-hybrid recall minus hybrid-without-ALS recall on the same targets, expressed in percentage points. A positive value means the full policy retrieves more targets overall at that pool size. This net difference does not count individual gained/lost requests or establish statistical significance.

| Fold | Difference at 100 (pp) | Difference at 500 (pp) | Difference at 1000 (pp) |
| ---: | ---: | ---: | ---: |
| 5 | +0.068 | -0.164 | -0.213 |
| 6 | -0.252 | -0.131 | -0.299 |
| 7 | -0.059 | -0.301 | +0.084 |
| 8 | -0.313 | -0.133 | -0.063 |
| 9 | -0.133 | +0.030 | -0.347 |

The pooled net Recall@1000 difference is **-0.167 percentage points**. Within the full hybrid's retained pool, **489 target hits** have ALS as their only contributing source. The latter is a source-evidence diagnostic, not an estimate of causal incremental performance.

The purpose of the hybrid experiment is to measure whether sources with different coverage patterns complement one another under a fixed candidate budget. In this run, Category leads at Recall@100, Hybrid without ALS leads at Recall@1000, and adding ALS to the equal-weight hybrid retrieves 99 fewer targets overall at 1,000 candidates while costing more. ALS supplies some unique hits, but fusion can displace targets from other sources within a fixed budget. The observed net recall and cost do not justify adding ALS to this equal-weight policy. The ALS source and full hybrid remain comparison references; this result does not support a production choice or establish that hybridization itself is beneficial for every budget.

## Cold retrieval: folds 5–9

Primary denominator: **715,331 first-time targets**, with **663,319** targets in the training-time catalog. ItemKNN, ALS and category sources return empty pools for empty context. Popularity provides the explicit fallback in each hybrid. All cold targets are evaluated against the shared empty-context lists; latency uses 100 repeated empty-context requests per fold rather than millions of duplicate model calls.

| Generator | Recall@100 | Recall@500 | Recall@1000 |
| :--- | ---: | ---: | ---: |
| ItemKNN | 0.000000 | 0.000000 | 0.000000 |
| Exact ALS | 0.000000 | 0.000000 | 0.000000 |
| Category | 0.000000 | 0.000000 | 0.000000 |
| Recent popularity | 0.032030 | 0.084230 | 0.122012 |
| Global popularity | 0.031817 | 0.078551 | 0.116206 |
| Hybrid | 0.033435 | 0.084899 | 0.119838 |
| Hybrid without ALS | 0.033435 | 0.084899 | 0.119838 |

The two hybrids are identical for cold requests because the personalized sources return empty lists. Recent popularity has the highest observed Recall@1000 here; the hybrid has higher Recall@100. Fusion does not improve every candidate budget.

## Snapshot fitting and factor memory

Factor memory measures loaded ALS user and item arrays only. It excludes sparse matrices, catalogs, candidate objects and other process allocations, and does not verify the project's 2 GiB serving-process budget.

| Fold | ItemKNN fit (s) | ALS fit (s) | ALS factor arrays (MiB) | Evaluation (s) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.99 | 68.20 | 107.57 | 168.15 |
| 2 | 7.75 | 114.92 | 194.15 | 262.27 |
| 3 | 14.93 | 170.52 | 274.31 | 372.67 |
| 4 | 21.38 | 203.46 | 348.78 | 427.61 |
| 5 | 39.08 | 250.19 | 423.01 | 491.54 |
| 6 | 42.08 | 286.62 | 502.44 | 521.89 |
| 7 | 53.37 | 311.29 | 576.18 | 618.82 |
| 8 | 70.05 | 377.92 | 652.74 | 692.15 |
| 9 | 76.91 | 387.07 | 727.42 | 722.29 |

## Nine-fold diagnostic trend

These transferred configurations and fixed retrieval policies are measured across all nine periods for engineering diagnostics. This table is not a nine-fold model-selection result.

| Fold | Warm targets | ItemKNN Recall@1000 | ALS Recall@1000 | Hybrid Recall@1000 | Without ALS Recall@1000 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5,346 | 0.062851 | 0.152637 | 0.219978 | 0.207819 |
| 2 | 7,201 | 0.065408 | 0.148590 | 0.230385 | 0.218997 |
| 3 | 8,602 | 0.057196 | 0.124390 | 0.212276 | 0.214136 |
| 4 | 9,635 | 0.058952 | 0.121017 | 0.213389 | 0.213804 |
| 5 | 10,349 | 0.053822 | 0.114697 | 0.222244 | 0.224370 |
| 6 | 10,720 | 0.051959 | 0.109422 | 0.213899 | 0.216884 |
| 7 | 11,950 | 0.051130 | 0.111464 | 0.210042 | 0.209205 |
| 8 | 12,765 | 0.047630 | 0.108656 | 0.210889 | 0.211516 |
| 9 | 13,539 | 0.047197 | 0.103405 | 0.203412 | 0.206884 |

## Reproducibility and verification

[The result artifact](../benchmarks/retrieval/candidates.json) records exact hit counts, per-fold catalog coverage, source contributions, runtime versions, selected sweep hashes, the full rolling-manifest fingerprint, retrieval policy and implementation fingerprint. Fold checkpoints are atomic and resume refuses changed provenance or policy. Pooled recall is derived from integer hit totals.

Validation covers unknown context, seen/catalog filtering, exact-score ties, exhausted pools, finite empty-cohort metrics, cold shared-pool equivalence, causality, mixed-type ID normalization in validation and evaluator histories, actual CLI fitting, atomic writes, resume and tampered checkpoint/fold rejection. The full suite passed 180 tests in the `ecommerce-recsys` environment on 2026-10-06 (Python 3.13.15, `implicit` 0.7.3); Ruff lint and format checks also passed. The [verification artifact](../benchmarks/retrieval/verification.json) records the source snapshot, commands, fingerprints and resume check. Published source identity normalizes LF line endings; published retrieval JSON retains its exact bytes so the recorded file hashes survive checkout.

```sh
python -m pip install -e ".[dev]"
python scripts/benchmark_candidates.py
python -m scripts.verify_candidate_artifact
pytest -q --basetemp=.local/pytest_m7_final
ruff check .
ruff format --check .
```

Prepared rolling folds and the completed M5–M6 sweeps are prerequisites. Pass `--input-path` and `--fold-dir` for external data locations. Use a fresh `--output` when changing code, runtime versions or policy. See the [candidate-generation design](CANDIDATE_GENERATION.md) for the complete contract.

## Limitations

Candidate recall bounds the recall attainable by a final ranker using that candidate pool; it does not establish final ranking improvement. Category retrieval uses pooled training popularity across history categories; it is not identical to the earlier category baseline's traversal/backfill policy. ALS requires a learned user vector; session history filters newly seen products without updating that vector. Eligibility means observed by the cutoff, not live inventory validation.

Independent confirmation requires an evaluation period whose outcomes have not been inspected.
