# ANN retrieval feasibility report

| Field | Result |
| :--- | :--- |
| Status | No-go after the predeclared fold-1 speed gate; no ANN source was adopted |
| Measured | 2026-10-09, local Windows CPU run |
| Model | Selected exact Two-Tower, dimension 128 and maximum history 50 |
| Index pilot | Faiss CPU 1.15.1 HNSW, inner product, one thread |
| Validity | Development-period feasibility screen only; no folds 5–9 ANN results |

## Question and decision

The feasibility policy asks whether approximate retrieval can materially
reduce the cost of exact Two-Tower retrieval without losing its candidate
target hits. The roadmap makes ANN conditional on measured exact-search
cost. The screen first profiled exact retrieval on folds 1–4, then
compared four fixed ANN settings with exact retrieval from the **same fitted model** on fold 1. The pilot used the same
1,000 sampled warm requests for both paths, with 3,000 timed calls per path and
configuration after warmup.

The plan's adoption gate requires ANN p95 at budget 1,000 to be at most half the
paired exact p95 on **every** development fold, plus separate target-hit gates.
All four configurations failed that speed condition on fold 1. Since each must
pass every development fold, no configuration can qualify. The runner recorded
`no-go: all configs fail fold-1 paired p95 gate` and did not open folds 2–4 for
ANN or folds 5–9. This is a screening result, not a four-fold quality comparison
or an independent validation result. The no-go keeps exact Two-Tower as the
model reference; it does not claim exact Two-Tower is the best retriever in the
project. The hybrid without ALS had higher Recall@1000 on the shared warm
cohort, under a different multi-source policy.

## Exact-cost profile: development folds 1–4

Each row times `generate(context, limit=1000)` after one warmup call per sampled
request. Sampling takes 250 requests from each quartile of full distinct seen
history length, using a recorded seed and request digest. The 1,000 requests in
each fold are timed three times. Percentiles are computed within each fold from
its 3,000 calls using linear interpolation; they are not pooled across folds.

| Fold | Train catalog items | Model fit (s) | Exact p50 (ms) | Exact p95 (ms) | Exact p99 (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 75,003 | 84.17 | 6.380 | 8.426 | 11.390 |
| 2 | 110,887 | 180.46 | 9.018 | 13.806 | 18.902 |
| 3 | 136,425 | 264.81 | 9.413 | 12.083 | 16.644 |
| 4 | 156,293 | 360.11 | 10.082 | 13.550 | 17.450 |

The declared exact-cost trigger was p95 above 10 ms on at least one development
fold. Folds 2–4 crossed it, so the ANN pilot proceeded. This threshold is an
offline engineering trigger, not a serving SLA.

## ANN compatibility and paired fold-1 pilot

The first library candidate, `hnswlib` 0.8.0, had only a source distribution on
PyPI and could not build on this Windows host because Microsoft Visual C++ Build
Tools were unavailable. Faiss CPU 1.15.1 supplied a Python 3.13 Windows wheel;
its local inner-product HNSW build/query and index save/load smoke tests passed.
Linux CI has not run, so Faiss was installed only in the local `ecommerce-recsys`
environment and has **not** been added to `pyproject.toml`.
[hnswlib release files](https://pypi.org/project/hnswlib/#files) and
[Faiss CPU release files](https://pypi.org/project/faiss-cpu/#files) document the
package distribution formats.

The fold-1 pilot trained the same selected Two-Tower once, built each index
from its 75,003 train-catalog item vectors, and interleaved exact and ANN calls
over identical request contexts. ANN re-scored its retrieved shortlist by exact
Two-Tower dot product, filtered seen items, and used item ID as the tie-break.
Every configuration used construction effort 200, shortlist overfetch starting
at 2,000, and one numerical thread.

| HNSW graph degree | Search effort | Exact p95 (ms) | ANN p95 (ms) | ANN / exact p95 | Index build (s) | Serialized index (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 2,000 | 9.311 | 14.844 | 1.594 | 25.23 | 46.94 |
| 16 | 4,000 | 9.659 | 35.411 | 3.666 | 22.82 | 46.94 |
| 32 | 2,000 | 10.698 | 17.954 | 1.678 | 37.46 | 56.09 |
| 32 | 4,000 | 9.378 | 34.278 | 3.655 | 29.98 | 56.09 |

The "Search effort" column is the configured floor. The adapter raises the
effective effort only when adaptive overfetch doubles the shortlist; in this
pilot `max_effective_ef_search` in the artifact equals the configured value in
all four rows, so no doubling was triggered.

The fastest measured ANN configuration was still slower than paired exact
retrieval at p95. Its mean call time was 12.723 ms versus 7.487 ms for exact.
No positive per-query time saving exists in this pilot, so a finite build-cost
break-even request count cannot be calculated. The index adds build time and
serialized bytes; loaded-process RSS was not measured because the adoption gate
already failed. Serialized index size is not whole-process memory.

The first timed repetition also recorded target hits in the 1,000-request
**sample**, solely as a diagnostic of the candidate paths:

| Graph degree / search effort | Exact hits @100 / @500 / @1000 | ANN hits @100 / @500 / @1000 | Exact-only hits @1000 | ANN-only hits @1000 |
| :--- | :--- | :--- | ---: | ---: |
| 16 / 2,000 | 28 / 47 / 64 | 28 / 46 / 65 | 6 | 7 |
| 16 / 4,000 | 28 / 47 / 64 | 28 / 46 / 65 | 4 | 5 |
| 32 / 2,000 | 28 / 47 / 64 | 28 / 44 / 62 | 8 | 6 |
| 32 / 4,000 | 28 / 47 / 64 | 29 / 46 / 66 | 3 | 5 |

An approximate pool can gain one target while losing another, so a higher
sample hit total does not imply exact top-N fidelity. This sample is not the full
5,346 warm windows in fold 1, nor the complete 30,784 development windows. The
planned pooled and per-fold hit-retention gates were not evaluated after the
independent speed gate failed.

## Provenance and reproduction

The [exact profile artifact](../benchmarks/retrieval/m9_profile_v1.json) contains
all four development-fold rows and the cost-trigger decision. The
[ANN pilot artifact](../benchmarks/retrieval/m9_ann_pilot_v1.json) contains all
four fold-1 configurations, paired latency samples, sample hits, build cost,
index bytes, model-vector SHA-256, and the no-go decision. Both bind the rolling
manifest, processed input, published Two-Tower selection lock, runtime, policy and
relevant source hashes; results and checkpoints have content fingerprints and
atomic writes. These two artifacts carry their own runner-internal checkpoint
validation (`results_sha256` plus policy/runner binding in each script); they
are outside the scope of `verify_candidate_artifact`, which covers the hybrid
`candidates.json` comparisons. Index binaries and scratch probes remain outside
Git.

The exact-profile and ANN-pilot runner fingerprints match source commit
`7b27f141f8d1a331bc4ebe0e924db59eeeef9e42`. Reproduce the frozen v1
artifacts in a separate checkout of that commit, following its version of
this report and the [two-tower report](TWO_TOWER_REPORT.md). Use the Python
3.13 `ecommerce-recsys` environment and the optional `faiss-cpu==1.15.1`
dependency. Current semantic script names have a different source fingerprint;
their guards reject resuming the published v1 artifacts. New runs must use
distinct artifact paths.

The optional ANN package is for reproducing the local pilot; it is not
a project dependency or evidence that Linux CI passed. Timing is local CPU
retrieval after model fitting and excludes data loading, model fit, final ranking,
network and API overhead. The recorded Python/library versions and one-thread
policy support reproduction, but the artifacts do not identify the CPU model or
measure serving-process RSS. No serving latency or production choice follows
from these measurements.
