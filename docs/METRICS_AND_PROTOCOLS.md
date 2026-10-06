# Metrics, protocols and model references

## Units and definitions

Accuracy, catalog coverage and pool rates are fractions in `[0, 1]` throughout
benchmark tables. For example, Recall `0.085063` corresponds to 8.5063%.
Behavioral dataset proportions use percentages with an explicit event or user
denominator. Relative metric improvements use percentages and are labeled as
relative changes; absolute recall differences use percentage points.

| Term | Definition | Denominator |
| :--- | :--- | :--- |
| HR@K / Recall@K | Target appears in the first K recommendations; the two are equal for this single-target task | Evaluated users or user-window targets |
| MRR@K | Reciprocal target rank, or zero for a miss | Evaluated users or user-window targets |
| NDCG@K | Log-discounted target gain, or zero for a miss | Evaluated users or user-window targets |
| Candidate Recall@N | Target appears in the first N eligible candidates | All evaluated targets, including unreachable items |
| Reachable recall@N | Candidate recall conditional on target eligibility | Targets present in the cutoff catalog |
| Coverage@K / Coverage@N | Unique recommended or retrieved items | Catalog items in the corresponding snapshot |
| Empty / full pool rate | Requests returning zero / the requested number of candidates | Requests in the specified cohort |

Latency is in milliseconds. Fit time is in seconds. Factor-array storage is in
MiB (`bytes / 2^20`); GiB means `bytes / 2^30`. Factor arrays exclude sparse
matrices, Python objects and other process allocations.

## Evaluation populations

> Compare models within the same protocol, cohort, snapshot and output budget.
> Historical leave-last-out, rolling Top-K and candidate retrieval answer
> different evaluation questions; their scores do not form one model ranking.

| Experiment | Targets and unit | Training boundary | Comparison role |
| :--- | :--- | :--- | :--- |
| Historical leave-last-out | One last event per eligible user; 200,028 users | Earlier within each user, without a global cutoff; targets can be repeats | Archived descriptive evidence |
| Rolling Top-K | First unseen future event per warm user-window; cold first events separate | All training events at or before the declared global cutoff | Nine-fold trend and folds 5–9 post-selection diagnostics |
| Rolling candidates | Same rolling targets and catalogs; budgets 100, 500, 1,000 | Same declared global cutoff | Target availability for downstream ranking |

Rolling folds 1–4 contain 30,784 warm targets; folds 5–9 contain 59,323.
Nine-fold pooled figures and five-fold figures have different populations.
Warm and cold outcomes are reported separately. The inspected later periods do
not provide an independent blind holdout.

## ALS configuration mapping

Every row below uses regularization 0.01 and seed 42.

| Reference label | Factors | Iterations | Protocol / purpose | Evidence |
| :--- | ---: | ---: | :--- | :--- |
| Historical baseline ALS | 64 | 20 | Leave-last-out M4 baseline | [Frozen baseline](../benchmarks/baseline/baseline_v1.json) |
| Historical selected ALS | 128 | 20 | M6 validation selection, followed by historical test | [Historical final run](../benchmarks/mf/als_final_v1.json) |
| Rolling reference ALS | 128 | 20 | Transferred nine-fold trend configuration | [Rolling reference](../benchmarks/rolling/results.json) |
| Rolling selected ALS | 128 | 40 | Selected on folds 1–4, measured on folds 5–9; transferred to M7 | [Rolling sweep](../benchmarks/rolling/als_sweep.json) |

The rolling 40-iteration configuration was retained by the declared HR/NDCG
selection rule. Its roughly one-hit selection advantage does not justify the
extra iteration cost by itself. It is an experimental reference, not a
production choice.

## Source and fallback semantics

| Component | Candidate behavior | Popularity fallback |
| :--- | :--- | :--- |
| Standalone Category recommender (Top-K) | Category-order traversal | Global backfill |
| Standalone ItemKNN recommender (Top-K) | Collaborative neighbors when history is indexed | Global recommendations for nonempty unindexed history |
| Standalone ALS recommender (Top-K) | Learned user/item scoring | Global recommendations for unknown users |
| M7 Category / ItemKNN / ALS sources | Only candidates from the named mechanism | Empty when required context or eligible candidates are absent |
| M7 hybrid | Fuses direct source lists and retains source evidence | Explicit global and recent popularity sources |

An empty direct-source pool measures that source's availability. It does not
mean the hybrid returns no recommendations. Cold hybrid requests have two active
sources, global and recent popularity; the three personalized sources are empty.

Source ranks are one-based positions **after source eligibility/seen filtering**.
Fusion uses those supplied ranks unchanged. Additional filtering of a cached
source list leaves gaps rather than promoting remaining products. Each hybrid
uses fixed source depth 1,000, so requests with the same context and different
output limits are prefixes of the same fused ordering.

## Timing scopes

All current Python timing summaries use linear-interpolation percentiles.
Matching percentile formulas does not make different workloads comparable.

| Measurement | Workload | Method | Scope |
| :--- | :--- | :--- | :--- |
| Historical / rolling Top-K warm latency | Maximum K = 20 | Direct recommendation call per evaluated user | Model call and adapter |
| M7 direct-source warm latency | Maximum N = 1,000 | Direct source call per warm request | Retrieval, filtering and candidate records |
| M7 hybrid warm cost | Maximum N = 1,000 | Sum of measured constituent source calls plus fusion | Serial cost estimate; shared source outputs reused |
| M7 cold latency | Empty context, maximum N = 1,000 | 100 repeated calls per fold | Repeated shared-pool workload; all cold targets still enter accuracy metrics |

Compare timings only within a matching row/workload and runtime setting. Do not
rank M4 versus M7, or warm versus cold, by their p95 values. These measurements
exclude fitting, loading, final ranking and HTTP/network overhead; serving
latency requires a separate end-to-end measurement. Per-fold percentile ranges
are descriptive ranges, not pooled percentiles.
