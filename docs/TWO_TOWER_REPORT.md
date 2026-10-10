# Two-tower candidate retrieval report

| Field | Value |
| :--- | :--- |
| Status | Published v1 development sweep, selection lock and folds 5–9 diagnostic complete |
| Measured | 2026-10-09 |
| Selected Two-Tower | Dimension 128, maximum history 50 |
| Selected ALS comparator | 128 factors, 40 iterations, regularization 0.01 |
| Validity | Folds 5–9 are post-selection diagnostics, not blind validation |

## Scope and validity

This experiment measures whether the next eligible warm-user target appears in
an exact retriever's top 100, 500 or 1,000 candidates. It measures candidate
recall, not final ranking quality or Top-20 recommendation quality. Two-Tower and ALS use
the same 59,323 warm user-window targets and fold-specific train-time catalogs
on folds 5–9. The denominator includes unreachable targets; the 54,412
reachable-target count is shown separately for context.

Folds 5–9 had been inspected before configurations were locked. All results on
those folds are post-selection diagnostics. The 1–4 development sweep selected
the configuration under the predeclared rule; no claim of blind validation or
statistical significance is made. Independent confirmation requires a later,
previously unseen time period.

Earlier exploratory Two-Tower metrics are excluded. Review found that the
inference context deduplicated history before encoding and could therefore lose
repeated-event order. The corrected v1 path preserves ordered events for
Two-Tower while retaining the existing deduplicated history contract used by
the hybrid candidate sources and ALS. Refit clears stale model state, full
prior history is excluded from negative sampling, and defensive per-batch skips
are counted.

ALS v2 artifacts are reused as the comparator. The ALS fitting and scoring path,
data, fold manifest, runtime, grid and candidate budgets are unchanged. The v1
selection lock binds the full SHA-256 values of the ALS development and
diagnostic artifacts and records their original code and policy fingerprints.

## Model and selection policy

The user tower mean-pools embeddings for recent distinct items. The item tower
combines item-ID and train-time category embeddings. Their L2-normalized vectors
are scored with exact dot products over the eligible fold catalog. Unknown
categories map to a reserved bucket.

Training examples predict a user's first occurrence of an item after strictly
earlier history. Events sharing the target timestamp are excluded from history
and from negative candidates. Five uniform negatives are drawn with replacement
from catalog items first seen strictly before the target timestamp, excluding
the full prior user history and every item in the same-timestamp positive bucket.
Examples with no eligible causal negative are skipped and counted. Interactions
and categories are bounded by each fold's cutoff.

The fixed training policy uses CPU, seed 42, one Torch thread, deterministic
Torch algorithms, three epochs, batches of 1,024 and five negatives. Adam and
SparseAdam use learning rate 0.003. The development grid crossed embedding
dimensions 64 and 128 with maximum histories 20 and 50. The selection rule was
highest pooled Recall@1000 on folds 1–4, then Recall@100, then lower model
complexity. It selected dimension 128 and maximum history 50 from 30,784
development user-windows, with Recall@1000 0.095861 (2,951 hits) and Recall@100
0.031315 (964 hits).

The existing eight-configuration ALS development sweep selected 128 factors,
40 iterations and regularization 0.01 under the same rule. It achieved
Recall@1000 0.133901 (4,122/30,784) and Recall@100 0.064287 (1,979/30,784) on
development folds. Its original v2 artifacts are referenced, not overwritten.

## Folds 5–9 diagnostic results

Recall is pooled as total target hits divided by all 59,323 warm user-windows.
Each target contributes at most one hit at each candidate budget.

| Retriever | Recall@100 (hits / 59,323) | Recall@500 (hits / 59,323) | Recall@1000 (hits / 59,323) |
| :--- | ---: | ---: | ---: |
| Two-Tower v1 (128, history 50) | 0.044485 (2,639) | 0.096185 (5,706) | 0.127640 (7,572) |
| ALS v2 (128 factors, 40 iterations, reg. 0.01) | 0.050705 (3,008) | 0.087116 (5,168) | 0.109216 (6,479) |

At budget 1,000, Two-Tower found 1,093 more targets than ALS across these
diagnostic windows, a difference of 0.018425 in pooled recall. At budget 100,
ALS found 369 more targets. These are descriptive differences on the
post-selection period; they do not establish a statistically reliable win.

The fixed hybrid without ALS achieved Recall@1000 0.213206 on the same
59,323 targets. Two-Tower is an additional model experiment, not the strongest
candidate policy measured in this repository. Its advantage over exact ALS at
budget 1,000 comes with lower Recall@100 and greater fitting time. This offline
comparison does not establish a serving choice.

| Fold | Warm windows | Two-Tower hits @100 / @500 / @1000 | ALS hits @100 / @500 / @1000 |
| ---: | ---: | ---: | ---: |
| 5 | 10,349 | 469 / 980 / 1,310 | 567 / 934 / 1,187 |
| 6 | 10,720 | 487 / 1,047 / 1,375 | 564 / 951 / 1,173 |
| 7 | 11,950 | 527 / 1,140 / 1,502 | 592 / 1,060 / 1,332 |
| 8 | 12,765 | 573 / 1,256 / 1,679 | 623 / 1,100 / 1,387 |
| 9 | 13,539 | 583 / 1,283 / 1,706 | 662 / 1,123 / 1,400 |

The target set contains 54,412 targets present in their fold's training
catalog. On that reachable-only denominator, Recall@1000 is 0.139160 for
Two-Tower (7,572/54,412) and 0.119073 for ALS (6,479/54,412). The primary
reported recall above retains all 59,323 targets, including unreachable ones.

Both methods filled the requested budgets for every warm request. Two-Tower
catalog coverage at budget 1,000 ranges from 0.489816 to 0.594400 across folds;
ALS coverage ranges from 0.150408 to 0.157045. Coverage is per-fold unique
retrieved catalog items divided by that fold's eligible catalog, so the range
is reported rather than pooling incompatible fold catalogs.

## Cost and latency

Two-Tower fold fitting took 3,022.61 seconds in total across five independent
fold fits (per-fold range: 419.83–776.29 seconds). Its estimated resident model
bytes, including item vectors, ranged from 179,122,688 to 230,452,224 bytes per
fold. This is a model-array estimate, not whole-process memory.

`train_examples` counts distinct examples that reached an optimizer step in at
least one epoch. `skipped_examples` counts generated examples never used in an
optimizer step. `skipped_batch_sampler_attempts` counts sampler failures across
epochs separately; all 16 development rows and five diagnostic rows have zero
such failures.
These fields do not count optimizer updates.

The reused ALS diagnostic fitting took 1,592.76 seconds total (per-fold range:
219.23–412.43 seconds). `factor_array_bytes` ranged from 443,559,424 to
762,749,952 bytes per fold. These byte counts cover factor arrays, not total
process memory.

The artifacts report per-fold, per-request local retrieval latency. Two-Tower
p95 ranged from 14.28 to 21.14 ms; ALS p95 ranged from 12.10 to 16.05 ms. These
measurements are offline exact-scoring timings on this runtime and hardware.
The Two-Tower and ALS p95 values came from separate runs, so they are descriptive
cost observations rather than a controlled serving comparison.
They exclude model fitting, final ranking, network and service overhead and are
not serving SLAs. They should not be compared with the earlier Top-20 ranking
latency because the workloads differ.

## Artifacts and provenance

| Artifact | Role |
| :--- | :--- |
| [`two_tower_sweep_v1.json`](../benchmarks/retrieval/two_tower_sweep_v1.json) | Complete folds 1–4 development sweep, 16 configuration-fold comparisons |
| [`m8_selection_lock_v1.json`](../benchmarks/retrieval/m8_selection_lock_v1.json) | Locked Two-Tower and ALS selections, rule and input/code/policy hashes |
| [`two_tower_diagnostic_v1.json`](../benchmarks/retrieval/two_tower_diagnostic_v1.json) | Complete folds 5–9 Two-Tower post-selection diagnostics |
| [`als_candidate_sweep_v2.json`](../benchmarks/retrieval/als_candidate_sweep_v2.json) | Reused complete ALS development sweep |
| [`als_candidate_diagnostic_v2.json`](../benchmarks/retrieval/als_candidate_diagnostic_v2.json) | Reused complete ALS folds 5–9 diagnostics |

The Two-Tower diagnostic binds manifest SHA-256
`5e6a22d5afaca8bc52b1103ad17bed247d9553756945dbbce99981d19bf1f9c3`, processed
input SHA-256 `5fdbf3e6b8cfdb80fe0aca1066786ac9c6c72326943f988529accfccfaf77a7e`,
runner SHA-256 `7528b0b7fea1d2bbc53db4a417d11e94fceaca023966cee86eea4f2579b64dda`,
and policy SHA-256
`6cdff58c9c4df8ab47bb986f6fb8b6908b8f40593775f6b455c7aefea6067cd6`. Its
selection-lock SHA-256 is
`0f851bde574ece8d3e762a4f9d21a4297868ca1af1bf775b193163ee19de97db`. The
artifact records Python 3.13.15, NumPy 2.5.2, pandas 2.3.3, SciPy 1.18.1 and
Torch 2.14.1+cpu.

## Reproduction of the published artifacts

The published runner fingerprint above matches source commit
`7b27f141f8d1a331bc4ebe0e924db59eeeef9e42`. Reproduce these frozen v1
artifacts from that commit in a separate checkout, using the commands in its
version of this report and Python 3.13 in the `ecommerce-recsys` environment.
The current source uses semantic script names and has a different fingerprint;
its guards intentionally reject resuming the published v1 files. New runs
must use distinct artifact paths. The lock validates the reused ALS evidence
without relabeling its v2 results.
