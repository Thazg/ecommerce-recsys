# ANN retrieval feasibility plan

**Status:** Feasibility screen completed with a no-go decision. This document
records the experiment plan; the [ANN feasibility report](ANN_RETRIEVAL_REPORT.md) records the
measured exact profile and fold-1 ANN pilot. No ANN index was selected for the
retrieval pipeline.

## Goal and decision boundary

M9 tests whether an ANN index makes the selected M8 Two-Tower retriever materially
cheaper at candidate budgets 100, 500 and 1,000 while retaining nearly all of its
exact-search target hits. The comparison is **ANN Two-Tower versus exact Two-Tower
from the same fitted model**, on the same fold, catalog, user vector and request.
Exact ALS and the M7 hybrid remain context, not substitutes for this paired
comparison. Candidate recall is not final Top-20 quality.

The [roadmap](ROADMAP.md) makes ANN conditional on exact retrieval cost. The
[two-tower report](TWO_TOWER_REPORT.md) records exact Two-Tower p95 of 14.28–21.14 ms
on folds 5–9, but its ALS timings came from separate runs. Those figures motivate
a controlled profile; they do not establish an online latency problem. The
[charter](PROJECT_CHARTER.md) sets 300 ms p95 for a future full serving path; it
cannot be used as an M9 retrieval benchmark result.

### Predeclared go/no-go rules

1. **Profile exact retrieval first.** Refit the locked M8 configuration and
   measure exact full-catalog scoring in the M9 harness. Use warm requests from
   development folds 1–4, a fixed sampling seed, the same process and identical
   context construction intended for ANN. If exact p95 is at most 10 ms on every
   measured development fold, publish a no-go profile and stop: an additional
   index is not justified by this offline workload. This 10 ms threshold is an
   M9 engineering trigger, not a serving SLA.
2. **Run a small ANN pilot only if the exact-cost trigger is met.** Verify that
   the candidate library installs and works with this repository's Python 3.13
   environment on Windows and Linux CI before adding a dependency. If it does
   not, record the failure and stop rather than silently changing environments.
3. **Select on folds 1–4 only.** An ANN configuration is eligible if pooled
   target Recall@100 and Recall@1000 each retain at least 99% of the paired exact
   Two-Tower hits, no development fold retains less than 97% at either budget,
   and the paired warm-request p95 at budget 1,000 is at most half of exact p95
   on every development fold. These are prospective engineering gates, not a
   claim of statistical non-inferiority. Among eligible configurations, choose
   the lowest median of the four per-fold p95 values; tie-break by smaller
   serialized-index bytes, then lower graph degree, then lower search effort.
   Do not pool latency percentiles across folds. If none passes, publish a no-go
   result and keep exact retrieval as the reference.
   Because every fold must pass the p95 gate, the sweep may stop after a complete
   paired pilot of all four configurations on fold 1 if all four fail that fold's
   gate. Publish the pilot's sample size, timing scope and no-go decision; do
   not call that a completed four-fold quality sweep.
4. **Assess cost, not only query speed.** Report build time, index bytes, loaded
   process RSS, and the break-even query count
   `build_time / (exact_mean_query_time - ANN_mean_query_time)` when the
   denominator is positive. No production request volume exists yet, so do not
   claim that build cost will be recovered in service.

The thresholds above must be frozen in the M9 policy before reading ANN scores
from folds 5–9. Folds 5–9 were already inspected in M4–M8, so any locked M9
figures there remain **post-selection diagnostics, not blind validation**.

## Inputs and retrieval contract

| Input or output | M9 rule |
| :--- | :--- |
| Model | Refit the selected M8 Two-Tower: dimension 128, maximum history 50, fixed training policy. Do not retune embeddings in M9. |
| Catalog | Use only eligible item IDs and category metadata from each fold's verified train-time snapshot. Index only that fold's fitted item vectors. |
| Query | Use the same `RetrievalContext.ordered_history` and shared latest-occurrence encoder as exact M8. Exclude full seen history from returned candidates. |
| Scores | Retrieve a shortlist by inner product, then recompute exact Two-Tower dot products for shortlisted items; sort by descending score and ascending string item ID. |
| Output | Return at most the requested budget as unique, unseen, catalog-eligible `Candidate` records with finite scores and `two_tower_ann` source evidence. No hidden popularity fallback. |
| Budgets | Build one ranked pool up to 1,000 per request and evaluate its prefixes at 100, 500 and 1,000. Smaller limits must be prefixes of the same ordering. |

The first pilot candidate is an HNSW index with inner-product search because the
M8 item and user vectors are L2-normalized. The library choice is provisional:
the Python 3.13/Windows/Linux smoke test and a same-vector exact parity test come
first. [hnswlib's API](https://github.com/nmslib/hnswlib) documents inner-product
space, graph degree, construction effort, search effort and seeded index builds.
[Faiss index documentation](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)
provides an alternative if the first library fails compatibility or measurement
requirements. Do not introduce a vector database or network service for this
offline experiment.

The search must request more than 1,000 neighbors to allow for seen-item
filtering. Predeclare a starting shortlist of
`min(catalog_size, max(2,000, 1,000 + seen_count))`, then double the request up
to the catalog size while fewer than 1,000 eligible items remain. Record the
number of index queries and whether the returned pool is short. A short pool is
an ANN outcome, not a reason to fill from exact or popularity candidates.
Set effective search effort to at least the requested shortlist size, and record
both configured and effective values when adaptive overfetch raises that size.
Unknown users and empty encoded history follow M8's direct-source behavior and
return `[]`. Index build/load failures must raise a visible error.

## Experiment sequence

| Phase | Work | Exit evidence |
| :--- | :--- | :--- |
| 0. Profile | Freeze workload, exact-cost trigger, hardware/runtime identity and query sampling; measure exact Two-Tower on folds 1–4. | `m9_profile_v1.json` with per-fold p50/p95/p99, mean, request count, catalog size and no-go/proceed decision. |
| 1. Compatibility pilot | Install the optional ANN library in `ecommerce-recsys`, check Windows and Linux CI import/build/query, fixed seed, one thread, ID mapping and save/load. | Smoke test and dependency/version record; no benchmark claims yet. |
| 2. Adapter | Add an ANN candidate source using the selected Two-Tower vectors and shared retrieval contract. Preserve the published exact-retrieval artifacts and record a new source fingerprint for subsequent runs. | Contract tests for causality, filtering, ties, prefixes, unknown users and short pools. |
| 3. Development sweep | Compare a small predeclared grid on folds 1–4: graph degree 16 or 32, construction effort 200, and search effort 2,000 or 4,000; use the same adaptive shortlist policy for every configuration. | Complete per-fold quality/cost rows, with one source and one cutoff identity per row. |
| 4. Lock | Apply the eligibility and tie-break rules above using only folds 1–4. Bind selected parameters and every relevant input/code/runtime hash. | `m9_ann_lock_v1.json`, or a documented no-go decision. |
| 5. Diagnostics | Only after lock, run the selected configuration and its paired exact comparator on folds 5–9. | Complete `m9_ann_diagnostic_v1.json` labelled `blind_holdout: false`; never use these scores to revise the selected configuration. |
| 6. Report | Explain quality loss/gain, speed, build and memory cost, benchmark limits and the decision to retain exact or use ANN in later experiments. | `ANN_RETRIEVAL_REPORT.md` and current-status/architecture updates after results exist. |

The first valid published M9 artifacts use `v1`. Aborted probes and compatibility
experiments stay under ignored `.local/`; they do not create a public `v2` or
overwrite M8 artifacts. A no-go after phase 0 or phase 3 is a complete M9
engineering outcome and does not require inventing diagnostic results.

## Measurement and selection details

- Use the existing nine rolling folds and unchanged warm targets. Development
  recall uses all 30,784 warm user-windows in folds 1–4; diagnostics, if reached,
  use all 59,323 warm user-windows in folds 5–9. Keep unreachable targets in the
  primary denominator and show reachable-target recall separately. Cold users
  are not part of this personalized Two-Tower comparison.
- Fit the model once per fold inside the M9 run; obtain both exact and ANN results
  from that same fitted model and catalog. M8 JSON metrics are not model weights.
  Do not compare an ANN run against an exact run fitted or timed separately.
- Compute pooled target recall from integer hit totals. Also report per-fold
  Recall@100/500/1000, ANN-only hits, exact-only hits, exact-hit retention,
  eligible-pool size, empty/full pool rates, and top-N item overlap. Distinguish
  target recall from overlap with the exact candidate set.
- For latency, sample 1,000 warm user-windows per fold with seed 42, stratified
  by quartiles of full seen-history length; record the selected request IDs or a
  digest. Warm the model and index, interleave exact and ANN calls in a seeded
  order, and repeat the paired sample three times. Compute each fold's p50/p95/
  p99 and mean from its 3,000 calls per source, with identical filtering,
  `Candidate` construction and output budget. Report hardware/runtime. Do not
  pool latency percentiles across folds or compare them to M8's separate-run p95.
- Measure model fit, index build, index load, query time and memory separately.
  Measure loaded-process RSS in an isolated process with identical model state;
  label index file size and vector-array bytes separately. The charter's 2 GiB
  serving RSS target is not validated by this offline process measurement.
- Record the paired exact baseline in the M9 artifact even if its numbers differ
  slightly from M8 timing. Keep M8 metrics and JSON unchanged.

## Reproducibility and failure checks

The runner should verify the full rolling manifest and fold files, processed
interaction hash, selected M8 configuration/lock and the exact item-vector
identity. Bind the M9 policy, ANN library/runtime versions, source fingerprints,
fold cutoff, catalog order, vector dimension and index parameters to each
checkpoint. Write fold checkpoints atomically and resume only if identity and
result-row hashes match. Persisted index files, if used, belong outside Git and
must be validated against their catalog/vector hashes before load.

Tests should cover a tiny exact-versus-ANN fixture; repeated and unknown history;
same-timestamp and cutoff boundaries; seen and catalog exclusions; float-score
ties; budget prefixes; exhausted catalogs; adaptive overfetch; index corruption;
stale vectors or catalog; wrong dimensions; deterministic rebuilds; interrupted
resume; and refusal to open folds 5–9 without a complete development artifact
and selection lock. An approximate search need not reproduce exact top-N, but
its output must always satisfy the retrieval contract.

Before a result is published, run the relevant tests and full `pytest`,
`ruff check .`, and `ruff format --check .` in the `ecommerce-recsys` environment.
Verify artifact hashes and Markdown links. Update `DECISIONS.md` only after an
index decision is implemented and measured; keep `ROADMAP.md` a roadmap and
`PROJECT_STATUS.md` a statement of current implementation.
