# Category-aware re-ranking on fixed learned candidate pools

## Question and evaluation boundary

This experiment asks whether a small category-novelty bonus can improve the
variety of the learned ranker's Top-20 list without materially reducing its
single-target ranking quality. It reorders the **same** full-hybrid candidate
pool and the same learned scores used in the [learned-ranking experiment](LEARNED_RANKING_REPORT.md).
It does not train a new ranker, retrieve additional items, or choose a
production serving policy. The cohort contains warm requests with an earlier
interaction history. Cold users are outside this comparison.

Each request uses its fold's training catalog and category snapshot at the
declared global cutoff. The future target is read only for evaluation. Unknown
categories receive no novelty bonus and do not count as distinct categories.
The selected ranker was trained chronologically on earlier labelled folds for
each development fold. For later folds, the [frozen ranker model](../benchmarks/ranking/ranker_diagnostic_v1.json)
trained on folds 1–4 supplies the scores without refitting.

## Fixed re-ranking policy

Candidates sort first by descending learned score and ascending item ID. The
re-ranker considers only the first 100 in this order and emits a Top-20 prefix.
For an item at zero-based shortlist rank `r`, the base utility is
`1 - r / max(shortlist_length - 1, 1)`. At each selection step, the item gets
an additional fixed bonus if its known category has not yet appeared in the
selected list. It never receives a bonus for an unknown category. Equal
utilities preserve the learned order. A bonus of zero reproduces the learned
Top-5, Top-10 and Top-20 exactly.

The utility uses **rank, not the magnitude of the learned score**. Two score
vectors with the same item order produce the same re-ranked list regardless
of their score gaps. This is a distinct-category re-rank, not
intra-list distance (ILD), maximal marginal relevance (MMR), or xQuAD: it
does not estimate pairwise item similarity or aspect probabilities. The bonus
also depends on shortlist length: one rank step is `1 / (n - 1)` for a
shortlist of `n > 1`. Its effective reach is therefore smaller in a short
pool, and an item below learned rank 100 cannot enter the output.

The bonus grid was fixed at `0`, `0.05`, `0.10` and `0.20`. Rank normalization
keeps the bonus interpretable when raw learned-score scales vary between
requests or folds. The first-100 and bonus values are experiment settings,
not an exhaustive search or a serving configuration.

The primary relevance metric is HR@20; MRR@20 and NDCG@20 retain rank
information. Since each request has one target, HR@K equals Recall@K. All warm
requests remain in the denominator, including targets outside the candidate
pool. The diversity metric is **distinct known-category slots@20**: sum of the
number of distinct known categories in each output, divided by
`20 × warm requests`. **Known-category item slots@20** uses the same
denominator and counts each selected item with known metadata. Empty output
positions remain in that denominator. Catalog item coverage@20 divides unique
recommended item IDs by that fold's train-time catalog size, so it is reported
per fold rather than pooled across changing catalogs.

## Development selection

The chronological development comparison trains the published selected
pairwise ranker on fold 1 and scores fold 2, then trains on folds 1–2 for
fold 3, and folds 1–3 for fold 4. All four bonus settings use identical
candidate rows and scores within each request. The [development artifact](../benchmarks/ranking/diversity_development_v1.json)
reconciles the zero-bonus order against the published learned-ranker
development artifact at K=5, 10 and 20.

The rule was fixed before scoring: a positive bonus must strictly increase
pooled distinct known-category slots; lose at most `0.001` absolute HR@20,
`0.001` absolute NDCG@20 and `0.005` absolute known-category item-slot rate
against zero. Among eligible values, choose more distinct-category slots,
then more hits, then higher NDCG, then the smaller bonus. If none qualifies,
select zero. The [selection lock](../benchmarks/ranking/diversity_selection_lock_v1.json)
binds the complete three-fold development artifact and this rule before later
folds are scored.

These are **pooled Top-20 gates**, weighted by the number of requests in each
fold. There is no per-fold constraint or HR@5/HR@10 gate. The known-category
item-slot gate did not bind any setting in this grid; every positive bonus
increased that rate. It should not be read as evidence of a measured
item-metadata trade-off.

| Bonus | Pooled warm requests, folds 2–4 | Hits@20 | HR@20 | NDCG@20 | Distinct known-category slots@20 | Known-category item slots@20 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 25,438 | 1,631 | 0.064117 | 0.030557 | 0.142995 | 0.840172 |
| 0.05 | 25,438 | 1,630 | 0.064077 | 0.030333 | 0.157630 | 0.847987 |
| **0.10, locked** | **25,438** | **1,625** | **0.063881** | **0.029905** | **0.176441** | **0.858051** |
| 0.20 | 25,438 | 1,608 | 0.063213 | 0.029251 | 0.216933 | 0.879806 |

The lock selected `0.10`. Relative to zero, it adds 17,016 distinct
known-category occurrences across the development requests, while losing six
Top-20 hits. The `0.20` setting exceeds the NDCG loss gate. These are tuning
scores: the retrieval configuration had already been selected using folds
1–4, and the diversity rule also uses folds 2–4.

The Top-20 gate obscures larger changes at shorter output budgets. For the
locked bonus, development hits@5 fell **809 → 781** (−28/25,438 requests),
and hits@10 fell **1,165 → 1,149** (−16/25,438). At K=5 the losses were
11/7,201 in fold 2, 7/8,602 in fold 3 and 10/9,635 in fold 4. These
figures were available during selection but were **not** part of its locked
gate; a different gate could have chosen a different setting.

## Post-selection diagnostic on folds 5–9

The locked `0.10` bonus and the zero-bonus learned order were scored on the
same regenerated full-hybrid pool and learned scores for **59,323 warm
user-windows**. Exactly **12,549** future targets were in those pools
(Candidate Recall@1000 **0.211537**); re-ranking cannot recover a target
outside the pool. Every fold's zero-bonus pool counts, Top-5/10/20 metrics and
empty-request count reconcile with the published [M7 candidate](../benchmarks/retrieval/candidates.json)
and [M11 ranker](../benchmarks/ranking/ranker_diagnostic_v1.json) artifacts.
The complete [re-ranking diagnostic artifact](../benchmarks/ranking/diversity_diagnostic_v1.json)
contains integer numerators, per-fold metrics, cost scopes, input/code hashes
and the selection-lock SHA.

| Fold | Warm requests | Learned hits@20 | Bonus hits@20 | Learned NDCG@20 | Bonus NDCG@20 | Learned distinct category slots@20 | Bonus distinct category slots@20 | Learned item coverage@20 | Bonus item coverage@20 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 10,349 | 636 | 634 | 0.029654 | 0.029259 | 0.119485 | 0.140120 | 0.167281 | 0.166793 |
| 6 | 10,720 | 603 | 603 | 0.026903 | 0.026819 | 0.123685 | 0.143405 | 0.157150 | 0.156700 |
| 7 | 11,950 | 654 | 653 | 0.026696 | 0.026411 | 0.128925 | 0.147490 | 0.163049 | 0.162267 |
| 8 | 12,765 | 675 | 676 | 0.025023 | 0.024618 | 0.125151 | 0.146479 | 0.152257 | 0.151966 |
| 9 | 13,539 | 669 | 670 | 0.024478 | 0.024394 | 0.129389 | 0.151256 | 0.152643 | 0.152282 |
| **Pooled 5–9** | **59,323** | **3,237** | **3,236** | **0.026383** | **0.026135** | **0.125625** | **0.146108** | — | — |

Pooled rates divide the summed numerators by the **59,323 requests** (or
`20 × 59,323` for category slots); they are not averages of the five displayed
rates. Catalog coverage uses each fold's own catalog denominator, so it has no
pooled row. The bonus adds **24,302 distinct known-category occurrences**
across outputs, or **0.020483** of the 20-slot denominator, while losing **one
Top-20 hit** (absolute HR@20 change **−0.000017** after rounding). It also
raises known-category item slots@20 from **0.958418** to **0.962514**; the
larger distinct-category gain therefore is not just a change in the number of
items with known metadata. Item catalog coverage falls slightly in every
fold. NDCG@20 falls by **0.000248** and MRR@20 by **0.000309** in the pooled
diagnostic. These are descriptive differences, not significance estimates.

| Output budget | Learned hits | Bonus hits | Learned HR | Bonus HR | Learned MRR | Bonus MRR | Learned NDCG | Bonus NDCG |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 1,649 | 1,638 | 0.027797 | 0.027612 | 0.015801 | 0.015464 | 0.018769 | 0.018459 |
| 10 | 2,374 | 2,385 | 0.040018 | 0.040204 | 0.017420 | 0.017125 | 0.022708 | 0.022512 |
| 20 | 3,237 | 3,236 | 0.054566 | 0.054549 | 0.018427 | 0.018118 | 0.026383 | 0.026135 |

The Top-5 loss and Top-10 gain show that the bonus changes positions within
the list. It does not improve every relevance metric, even where HR@20 is
nearly unchanged. The development gate selected an **offline trade-off option**
for comparison; these already-inspected later periods do not justify adopting
it as a production policy. The subsequent [complete-policy comparison](MODEL_POLICY_REPORT.md)
measures this option alongside the learned order and alternative source pools,
using a separate development route-selection lock and matched inference scope.

Only the locked `0.10` setting and its zero-bonus control were evaluated on
folds 5–9. The `0.05` and `0.20` settings have development results only;
their later-fold outcomes are unknown and cannot be inferred from this table.

## Cost, provenance and limits

The runner records retrieval-source fitting time and sums of local per-request
retrieval, feature construction, learned scoring and re-ranking call times.
For the selected bonus, the re-ranking function alone took **80.2 seconds**
over 59,323 requests (about **1.35 ms per call** in this run). The zero-bonus
control took 56.5 seconds in separate calls. These timings include the
re-ranker's input checks and sorting; they exclude metric accumulation, data
loading, history and feature-aggregate preparation, persistence, networking
and serving infrastructure. They are **not** end-to-end serving latency or a
serving SLA. Upstream fitting and retrieval dominate the offline workload.
The development grid called the re-ranker four times per request; the
diagnostic called it twice, for zero and the locked bonus. The selected call
was about 42% slower than the zero-bonus call in this run. Each invocation
sorts the learned scores; no shared pre-sort optimization was benchmarked.

| Fold | Retrieval-source fit s | Retrieval-call sum s | Feature-row sum s | Learned-score sum s | Selected re-rank sum s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 281.0 | 363.1 | 268.8 | 109.4 | 14.1 |
| 6 | 336.4 | 401.1 | 283.5 | 114.8 | 14.7 |
| 7 | 370.8 | 476.0 | 320.3 | 129.7 | 16.5 |
| 8 | 420.6 | 502.8 | 324.8 | 130.4 | 17.0 |
| 9 | 489.4 | 558.8 | 346.0 | 139.2 | 18.0 |

The comparison is warm-only and conditional on the first unseen future item
task. It holds the full hybrid fixed, including an expensive ALS source whose
incremental value was weak in an earlier retrieval ablation. A Top-100
shortlist limits what the bonus can move into Top-20; the values `100` and
`0.10` were not independently validated outside this grid. Category metadata
is incomplete and may reflect the Retailrocket property feed rather than a
stable product taxonomy. The same user may appear in several windows. Folds
5–9 were inspected during earlier milestones, so these results are
**post-selection diagnostics, not blind validation**. Independent confirmation
requires later untouched data. No paired confidence interval or live-user
effect is claimed.

The published M10/M11 artifact fingerprints used every Python file then in
`src/`. Later unrelated source additions changed that broad hash. This runner
checks that every original tracked source file still matches Git revision
`c80cebee3378ea9af7c9757802fa40e2c8594ae2`, recomputes the historical
M10/M11 fingerprints from that file set, and verifies the Parquet and JSON
hashes. Its own code fingerprint binds the M13 runner, re-ranker and that
historical dependency fingerprint, so unrelated future modules do not
invalidate this artifact. Diagnostic calls the zero-bonus control before the
locked bonus to keep timing order and JSON key order stable. It does not alter
the frozen upstream artifacts. Reproduction requires
that revision in the local Git history and the data files whose hashes match
the [M10 quality checkpoint](../benchmarks/ranking/m10_quality_v1.json).

From the repository root, with the Python 3.13 `ecommerce-recsys` environment
and those verified upstream inputs available:

```sh
python scripts/benchmark_diversity.py development
python scripts/benchmark_diversity.py lock
python scripts/benchmark_diversity.py diagnostic
pytest
ruff check .
ruff format --check .
```

The diagnostic runner requires the complete development artifact and lock,
verifies all fold files, and resumes only artifacts with matching policy and
provenance. It writes one atomic checkpoint per completed fold. A fresh build
of the frozen M10/M11 inputs should use their recorded source revision;
changing their artifacts in place would break this evidence chain.
