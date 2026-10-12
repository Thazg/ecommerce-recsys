# Sequential transition retrieval: ordered-history ablation

## Question and outcome

This offline experiment tests whether **the order of recent interaction-time
buckets** improves next-window candidate retrieval. Both policies use the same
transition table, the same last 20 timestamp buckets per returning user, the
same train-time catalog and the same candidate budget. The ordered policy
weights newer buckets more heavily; the control weights those buckets equally.
Neither has a popularity fallback.

The predeclared primary gate was pooled Candidate Recall@100 on rolling folds
5–9. The ordered policy found **3,799/59,323** warm targets (0.064039); the
equal-weight control found **3,824/59,323** (0.064461). The ordered policy lost
25 hits (−0.000421 in recall), and each of the five folds had fewer hits@100.
Both policies found **4,035/59,323** targets by rank 1,000 (0.068017), since
their candidate support is identical. **Decision: do not add the ordered
transition source to the hybrid.** This is a no-go for this fixed table,
lookback, weighting grid and task, not a claim that event order is generally
unhelpful.

These folds were inspected for earlier project models. All M12 later-fold
figures are **post-selection diagnostics, not blind validation** or statistical
significance evidence. No online serving or production source was built.

## Causal model and matched control

For each fold, the table uses only interactions at or before its train cutoff.
Repeated occurrences of an item at one user/timestamp are collapsed. All items
at that timestamp form one unordered bucket. Each item in a bucket contributes
one directed observation to each *different* item in the next timestamp bucket
of the same user. No transition is inferred within a timestamp. The source
normalizes each origin's outgoing counts into train-time transition
probabilities.
Adjacent buckets are consecutive **observed** user timestamps; the model
does not impose a maximum elapsed-time gap or define shopping sessions.

At inference, each candidate receives the sum of outgoing probabilities from
the user's last `H` **training** buckets, averaged across source items within a
bucket. The ordered policy multiplies each bucket by `decay ** age`, with the
newest bucket at age zero. The control uses weight one at every selected
bucket. The entire training history is filtered from the result, including
items older than `H`; catalog-ineligible items cannot enter the output. Results
sort by descending score and ascending string item ID for exact ties. Users
without supported transitions receive an empty list.

The target is each warm user's first previously unseen event in the next
rolling window. Unreachable items remain in the primary denominator. The
experiment measures a **direct candidate source**, not an addition to the M7
hybrid or an M11 ranking feature. Its Recall@100 cannot be presented as an
end-to-end Top-20 recommendation metric.

## Development selection and lock

The [rolling manifest](../benchmarks/rolling/manifest.json) defines four
development folds and five later diagnostic folds. The fixed grid contained
lookbacks `H={5,20}`, ordered decays `{0.5,0.8}`, and an equal-weight control
at each `H`. All six configurations were measured on folds 1–4. The frozen
rule selected the ordered configuration by pooled integer hits@100, then
hits@1000, fewer buckets and smaller decay; it paired the winner with the
equal-weight control at that winner's exact `H`.

| Development configuration | Hits@100 / 30,784 | Recall@100 | Hits@1000 / 30,784 |
| :--- | ---: | ---: | ---: |
| Ordered H=5, decay=0.5 | 1,874 | 0.060876 | 1,884 |
| Ordered H=5, decay=0.8 | 1,874 | 0.060876 | 1,884 |
| Ordered H=20, decay=0.5 | 2,012 | 0.065359 | 2,064 |
| **Ordered H=20, decay=0.8** | **2,023** | **0.065716** | **2,064** |
| Equal weight H=5 | 1,874 | 0.060876 | 1,884 |
| **Equal weight H=20 (paired control)** | **2,024** | **0.065748** | **2,064** |

The selected ordered configuration already trailed its matched control by one
development hit@100. The [development artifact](../benchmarks/retrieval/sequential_development_v1.json)
contains per-fold numerators, availability, coverage and cost for all six
configurations. The [selection lock](../benchmarks/retrieval/sequential_selection_lock_v1.json)
binds that complete artifact and the chosen pair before any M12 diagnostic
score was opened. Development accuracy reuses the rolling task and past-period
evidence; it is a tuning result, not an independent estimate.

## Post-selection diagnostic on folds 5–9

Both locked policies were evaluated on the same **59,323 warm user-windows**;
**54,412** targets were present in the corresponding train-time catalog. The
table gives integer target hits, including catalog-unreachable requests in
each fold's denominator.

| Fold | Warm requests | Ordered hits@100 | Equal hits@100 | Ordered hits@500 | Equal hits@500 | Both hits@1000 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 10,349 | 681 | 686 | 710 | 710 | 710 |
| 6 | 10,720 | 677 | 680 | 706 | 706 | 706 |
| 7 | 11,950 | 774 | 783 | 826 | 825 | 827 |
| 8 | 12,765 | 826 | 831 | 881 | 881 | 882 |
| 9 | 13,539 | 841 | 844 | 909 | 908 | 910 |
| **Pooled** | **59,323** | **3,799** | **3,824** | **4,032** | **4,030** | **4,035** |

| Budget | Ordered recall | Equal-weight recall | Ordered minus equal |
| ---: | ---: | ---: | ---: |
| 100 | 0.064039 | 0.064461 | −0.000421 |
| 500 | 0.067967 | 0.067933 | +0.000034 |
| 1,000 | 0.068017 | 0.068017 | 0.000000 |

The ordered and equal-weight policies retrieved the same set of items per
request; weighting only changed their order. Each returned **2,385,174** items
over all 59,323 requests, a mean of **40.207** per request. Each had **7,222**
empty requests (empty rate **0.121740**). The small support explains why
Recall@500 and Recall@1000 are nearly identical. The
[diagnostic artifact](../benchmarks/retrieval/sequential_diagnostic_v1.json)
also records reachable-target recall, coverage and per-fold fit/retrieval cost.
This source's target pool and budget differ from M11's fixed 1,000-item hybrid
pool; the two experiments answer different questions.

## Cost and limitations

The transition table contained 373,331 distinct directed pairs on fold 5 and
644,113 on fold 9. Per-fold fit time ranged from 5.5 to 9.7 seconds on the
local CPU run. Summed generation time over all later-fold warm requests was
8.77 seconds for ordered weighting and 8.26 seconds for equal weighting,
equivalent to measured means of 0.148 and 0.139 ms per call. These totals time
only table fitting and `generate` calls. They exclude Parquet loading, target
validation, user-history assembly, metric accumulation, persistence, networking
and an API. They are not end-to-end serving latency or an SLA, and the small
timing difference is not a speed claim.

Retailrocket contains many short histories and sparse next-bucket transition
support; this experiment does not separate those effects from any genuine lack
of order signal. The grid does not test learned sequence encoders, longer
sessions, alternative time gaps, reranking of a shared hybrid pool or a later
untouched period. Changing the grid after these scores would be another
exploratory analysis. The fixed no-go keeps the existing hybrid unchanged.
Building the table enumerates every distinct cross-bucket item pair; adjacent
buckets with `p` and `q` items require up to `p × q` observations. This limits
the approach on unusually large baskets.

## Reproduce and verify

With the prepared rolling files and Python 3.13 `ecommerce-recsys` environment:

```sh
python scripts/benchmark_sequential.py development
python scripts/benchmark_sequential.py lock
python scripts/benchmark_sequential.py diagnostic
pytest
ruff check .
ruff format --check .
```

The runner hashes the processed interactions, rolling manifest and fold files,
M12 code and fixed policy. Each phase writes a payload-hashed JSON file
atomically, and the diagnostic refuses a missing, incomplete or changed
development artifact and lock. It checkpoints each completed fold; a bounded
`--max-fold` run remains explicitly incomplete until fold 9. Raw CSV and
generated training data remain outside Git.
