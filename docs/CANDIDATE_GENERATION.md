# Candidate generation

## Design and acceptance criteria

M7 implements the retrieval stage specified in the project roadmap: request
candidate pools at budgets of 100, 500 and 1,000 products from the training-time
catalog, then evaluate retrieval independently of the later ranker. A budget is
an upper bound, not a guarantee that every source can fill the pool; ItemKNN's
mean warm pool was 40.07 products and 14.61% of warm requests were empty on folds
5–9. The implementation lives under
`src/ecommerce_recsys/retrieval/`, following the repository's package layout.

| Step | Deliverable | Acceptance condition |
| :--- | :--- | :--- |
| 1 | Shared candidate interface and immutable request/output records | Bounded, unique, unseen, catalog-eligible candidates with finite scores and source evidence |
| 2 | ItemKNN, exact ALS, category, global and recent popularity sources | Sources identify their actual contribution; personalized sources return empty when context is unavailable |
| 3 | Hybrid pool and popularity fallback | Deterministic fusion, retained per-source scores/ranks, explicit ablation without ALS |
| 4 | Rolling candidate benchmark | Recall@100/500/1000, reachable-target recall, availability, coverage, source contribution, fit time and retrieval latency |
| 5 | Regression and integration checks | Causality, filtering, ties, unknown users, pool exhaustion, checkpoint integrity and CLI resume tested |
| 6 | Measured report and architecture updates | Reproduction commands, measured outcomes and limitations |

## Interface and source behavior

`CandidateGenerator.generate(context, limit)` returns ordered `Candidate` records.
The context contains a user ID and the complete history available at the request
cutoff. Each candidate carries an item ID, retrieval score and `SourceEvidence`
records with the source name, source score and one-based source rank.

Source rank is the position in the source's eligible, seen-filtered list, not
its position in an unfiltered full-catalog ranking. Fusion preserves the supplied
rank; removing products from a cached pool does not promote remaining products.

The caller resolves the complete seen history before retrieval. A user ID alone
does not populate history for popularity, category or ItemKNN. The benchmark
constructs that context from the verified training snapshot.

All sources exclude seen items and items outside the supplied train-time catalog.
IDs are normalized to strings. Ties use ascending string item ID. Empty results
are valid when no eligible candidates exist. Invalid limits and nonfinite scores
are rejected.

ItemKNN uses the selected 20-neighbor, minimum-five-interactions model with
shrinkage 100. Exact ALS uses the selected 128-factor, 40-iteration model with
regularization 0.01 and seed 42. ALS scores the full item matrix by user/item dot
product; ANN is a later milestone. Extra request history is filtered in addition
to the stored training history.

M5–M6 selected these configurations using HR@20. M7 treats them as fixed
references; it does not claim they are optimized for Recall@1000.

Category retrieval pools products in the categories observed in the history and
orders them by training interaction count. Global and recent popularity use
interaction counts; the recent window is 30 days before the fold cutoff.
Category retrieval has no implicit global fallback. Neither ItemKNN nor ALS
attributes popularity recommendations to a personalized model.

The standalone M4–M6 recommenders have their own fallback policies. Direct-source
empty rates measure availability before explicit hybrid fallback. The
[source/fallback mapping](METRICS_AND_PROTOCOLS.md#source-and-fallback-semantics)
defines the distinction; cold hybrid requests have two active popularity sources.

## Hybrid policy

Each source supplies at most 1,000 candidates. The hybrid uses equal-weight
reciprocal rank fusion with score `sum(1 / (60 + source_rank))`, followed by
ascending item ID for ties. Raw cosine, ALS and count scores remain available as
evidence and are not added together because their scales differ.

The formula follows [Cormack, Clarke and Büttcher, SIGIR 2009](https://doi.org/10.1145/1571941.1572114).
The source pool depth of 1,000 and fusion constant 60 are fixed engineering
choices recorded in the runner's fingerprinted `POLICY`; M7 did not ablate either
value, so neither is presented as empirically optimal. The full hybrid combines
ItemKNN, ALS, category, recent popularity and
global popularity. A second hybrid removes ALS to measure its incremental recall
and cost. Popularity sources also provide the cold-user and sparse-history path.
M7 stops at candidate retrieval; the separate
[learned-ranking evaluation](LEARNED_RANKING_REPORT.md) compares final ordering
on fixed pools.

## Evaluation contract

Use the existing nine rolling folds and their exact warm/cold targets. Preserve
the interaction and fold SHA-256 checks, selected-model artifact checks and
global temporal and unseen-target guards. Folds 1–4 are development diagnostics;
folds 5–9 are reported separately as post-selection diagnostics. None of these
periods is an independent blind test.

With one target per user-window, Candidate Recall@N is the fraction of targets
present in the first N candidates. The primary denominator includes targets
outside the training catalog. A separate reachable-target recall conditions on
the target being in that catalog and explicitly states its smaller denominator.

Report candidate count, empty-pool and full-pool rates, catalog coverage and
retrieval p50/p95/p99. Source latency includes the adapter and filtering. Hybrid
latency includes all constituent retrieval calls plus fusion, excluding model
fitting, input loading and downstream ranking/API overhead. Shared source calls
are reused during evaluation; the hybrid cost is their measured sum plus fusion.

All timing summaries use the shared linear-percentile helper. Ranking Top-20,
candidate retrieval at 1,000 and repeated cold requests have different workloads;
their latency values must not be compared directly. The
[timing scope table](METRICS_AND_PROTOCOLS.md#timing-scopes) lists each measurement.

Cold requests have no user ID or history known to a fitted personalized model,
so all such requests share the same candidate lists. Evaluate all cold targets
against those lists without repeating millions of identical model calls. Measure
cold latency on repeated empty-context calls and label that sample separately.

Checkpoints are written atomically after each fold. They bind the dataset,
complete manifest, selected model configurations, retrieval policy, all package
Python sources, the preparation and benchmark scripts, project configuration and
evaluation sizes. Source fingerprints normalize CRLF to LF for checkout portability.
Resume refuses changed provenance, implementation or policy.

## Reproduction

```sh
python scripts/benchmark_candidates.py
pytest
ruff check .
ruff format --check .
```

Pass `--input-path` and `--fold-dir` if generated inputs reside elsewhere. The
benchmark uses the existing `benchmarks/rolling/` manifest and completed sweeps.
Results are written to `benchmarks/retrieval/candidates.json`.

Use a fresh `--output` path when changing the implementation, runtime versions,
cohorts or retrieval policy; checkpoint provenance prevents combining those runs.

## Boundaries

M7 supplies candidate records for a later ranker. It does not train a final
ranker, build an ANN index, persist serving model bundles or expose an HTTP API.
An unknown user with session history can use ItemKNN and category retrieval, but
ALS requires a learned user vector. Request history excludes newly seen products
without updating that learned vector. Catalog eligibility means observed by the
training cutoff, not verified live inventory availability.

Latency is a local offline measurement. ALS factor-array bytes exclude sparse
matrices, Python objects and other process memory; they do not certify the
project's 2 GiB serving-process budget.
