# Rolling temporal evaluation protocol

**Status:** Current benchmark for M4–M6, adopted 2026-10-04.

## Cohorts and time boundaries

The processed Retailrocket interactions are partitioned into ten consecutive windows using quantiles of distinct timestamps. The first window is training only. For each of the following nine folds, training contains **all events at or before the previous cutoff**; the evaluation window contains events after that cutoff and at or before the current cutoff. Every model trains on the same snapshot, and every target occurs strictly after all training events. No model is updated inside an evaluation window.

The primary **warm discovery** cohort has at least one training interaction. Its target is the first event in the evaluation window whose item is absent from that user's training history. Each user contributes at most one target per fold and may contribute in multiple folds. Repeat events and users without a qualifying unseen target are excluded from this cohort. We report both user-window targets and distinct users. This is a conditional discovery task, not an estimate of performance across all site visitors.

The **cold user** cohort has no training interaction. Its target is that user's first event in the evaluation window. Cold users are counted and reported separately; personalized models cannot use a history for these users. Global and recent popularity are evaluated as available cold-start fallbacks. Items absent from the training-time catalog are kept as targets and counted as unreachable by train-only recommenders.

## Candidate catalog and comparison

The candidate catalog contains item IDs observed in training. Category metadata is the latest known `categoryid` at or before the train cutoff from raw property events. Every M4–M6 model uses the same catalog, training interactions, warm targets, and K values within a fold. Models return only items that the user has not seen in training. Random, global popularity, recent popularity (30 days), and category popularity use fixed settings. ItemKNN and implicit ALS first ran historical reference configurations over all nine folds for descriptive comparison. Their sweeps use only folds 1–4; the winning configuration is frozen and then evaluated on folds 5–9. Selection uses pooled HR@20, with pooled NDCG@20 as the tie-break. The candidate sets and rule are fixed in `scripts/sweep_rolling.py`.

Metrics are HR, MRR, and NDCG at K = 5, 10, 20, plus catalog coverage and inference latency by fold. Pooled HR/MRR/NDCG weight each fold by its target count, so the unit is a **user-window**, not a unique person. A person can affect pooled metrics more than once. Coverage and latency are reported by fold rather than naively pooled.

**Validity of the reported comparison:** Reference HR/NDCG for folds 5–9 was inspected before sweep configurations were locked. The sweeps select using folds 1–4 only, but their five-fold results are exploratory post-selection diagnostics, not an independent blind test. Confirming a model choice requires a later time period whose outcomes have not been inspected.

## Reproduction and provenance

`scripts/prepare_rolling_data.py` creates `data/rolling/fold_XX` targets/catalog files and `benchmarks/rolling/manifest.json`. It resumes verified folds, writes new folds and the manifest atomically, and refuses to reuse changed source files or fold files. On a fresh unseen dataset, run `scripts/sweep_rolling.py` before viewing any fold 5–9 scores; it selects ItemKNN and ALS on folds 1–4 and evaluates the winner on 5–9. Then `scripts/benchmark_rolling.py` can produce a nine-fold diagnostic reference table. It refuses to expose folds 5–9 until both sweep artifacts are complete; `--max-fold 4` supports earlier engineering checks. `scripts/benchmark_rolling_cold.py` evaluates the two cold-start popularity fallbacks, resumes atomically, and also accepts `--max-fold 4` before sweeps are complete. The manifest records SHA-256 of processed interactions, both raw property files, and each generated fold file, plus fold boundaries, cohort sizes, and the share of warm targets outside the catalog. Benchmark artifacts bind to the full manifest fingerprint. Numerical worker pools are pinned to one thread during rolling benchmarks. Raw and generated data remain outside Git.

Earlier per-user leave-last-out artifacts use a different target definition and lack a global training cutoff. Their 200,028-user cohort and metrics are not directly comparable with this rolling benchmark.
