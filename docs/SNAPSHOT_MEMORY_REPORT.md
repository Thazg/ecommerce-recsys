# Snapshot reader memory assessment

## Scope

An opt-in [indexed reader](../src/ecommerce_recsys/artifacts/compact_runtime.py)
reduces Python object overhead while retaining the sealed fold-9 bundle and the
published context, retrieval, feature transform and ranking methods. The default
package/API loader and historical model/service/container sources remain unchanged.
This supports local operation. Cloud model hosting is outside the release scope
under [ADR-40](DECISIONS.md#adr-40--define-a-local-backend-release-with-public-static-demonstrations).

The [completed evidence](../benchmarks/deployment/snapshot_memory_validation_v1.json)
binds the original model manifest, current reader/profiler/test sources, numerical
environment and prospective measurement policy. The bundle remains
`retailrocket-fold09-v1`, manifest SHA-256
`84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe`.

## State representation

All 1,265,556 snapshot users and 224,190 items remain addressable. Full seen-item
rows, original float32 factors, neighbor order/similarities and source eligibility
are retained. The 101 verification contexts are a finite sample, not a reduction
of the stored population.

- User/item counts and timestamps use read-only numeric columns with shared ID
  indexes. Lookups return Python integers to preserve the frozen feature behavior.
- Event-type counts use numeric columns and temporary row views, preserving the
  original absent-zero lookup semantics.
- User/category affinities use sparse row pointers and sorted category codes.
- Source catalogs share one immutable set; neighbor IDs reuse catalog strings.
- The original inventory/schema/semantic validation and numerical compatibility
  guards run before constructing compact state. Loading requires an external
  manifest pin. Existing bundle bytes, factor precision and model policy are retained.

The entry point is `load_compact_bundle(path, expected_manifest_sha256=...)`.
It reuses the original `LoadedBundle.context`, `trace` and `recommend` methods.
Existing service factories can explicitly inject this reader; the supported
launcher still selects the original loader. No public exposure is introduced.

## Paired local measurement

Measured on **2026-10-23**, Windows/AMD64, Python 3.13.15 and implicit 0.7.3,
using the existing `ecommerce-recsys` environment. Each reader runs in a fresh,
sequential child process with one numerical thread and cache disabled. Baseline
runs first; this single pair does not estimate measurement variability.

The parent samples child-process RSS at a nominal 50 ms interval, independently
of the model process GIL. Explicit ready/final snapshots supplement the samples.
The declared maximum permitted sample gap is 200 ms. Import, validation and
restoration belong to startup; reference tracing and the post-reference settle
belong to the loaded phase. Parent/whole-host memory is outside the RSS values.

| Measurement | Original reader | Indexed reader |
| :--- | ---: | ---: |
| Ready RSS, GiB | 2.091 | 1.455 |
| Loaded/reference sampled peak RSS, GiB | 2.101 | 1.459 |
| Startup sampled peak RSS, GiB | 2.322 | 1.779 |
| Load time including imports and collection, seconds | 23.663 | 17.570 |
| RSS sample count | 647 | 509 |
| Largest sample gap, milliseconds | 69.872 | 69.950 |
| Exact producer references matched | 101/101 | 101/101 |

Ready RSS decreased by **651.727 MiB
(30.43%)**. The indexed
reader's measured loaded and startup peaks are below 2 GiB on this host.
These observations do not replace the earlier Linux API RSS failure or certify
Linux/container/target-host memory for the new reader.

Each reader matches all 100 warm and one cold producer trace, including the full
candidate pool/order, source-evidence digest, feature/score array digests, route
and Top-20 output. This is exact same-host finite reference parity. Full-fold
quality was not recomputed; inspected later-fold diagnostics remain unchanged.

The worker also records total full-trace time for warm/cold contexts. Those
calls include feature construction and parity digests, without HTTP transport.
They do not establish request percentiles, representative throughput or a serving
SLA. No latency acceptance or improvement claim is inferred from the single pair.

## Verification and failure behavior

The final Windows unit profile passed **1,247 cases**, with three existing
symlink-privilege skips. It includes 37 new cases covering fitted-source/feature/
trace/prefix parity, explicit HTTP loader injection, empty/missing sparse
lookups, read-only arrays, mandatory pins, component tampering, resource bounds,
source/receipt drift, duplicate fields, non-overwriting publication and worker
cleanup after timeout or sampler setup failure. Ruff lint and formatting pass.

The profiler refuses partial reference coverage, parity differences, source or
environment changes, resource gaps and inconsistent timing/RSS scopes. Child
workers are reaped before a completed assessment is published. Fresh publication
is exclusive and file-synced; directory-entry power-loss durability is not claimed.
The receipt contains no raw snapshot user IDs or per-request outputs.

Fitted HTTP coverage here uses an embedded synthetic model. The new reader's
real-bundle measurement is package inference, not a fresh real HTTP, Docker,
Linux or cloud qualification. The frozen API/default loader has not been switched.

## Reproduction

Run from the repository root in `ecommerce-recsys`, with the original external
bundle and numerical versions. Create `.local/` if needed and choose an unused
output path. No training data, fitting or cloud account is used.

```sh
python scripts/profile_snapshot_memory.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/snapshot-memory-repeat.json
```

To check source/input/receipt integrity from the matching producer source
snapshot, without loading a model or repeating memory measurements:

```sh
python scripts/profile_snapshot_memory.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --check benchmarks/deployment/snapshot_memory_validation_v1.json
```

The check hashes the complete original bundle and recomputes current source and
receipt consistency. It does not rerun the worker observations. Preserve earlier
receipts and use a new path after implementation or measurement-policy changes.
Its full-package identity includes the educational recommenders; subsequent
changes outside inference also make the original check reject. The historical
paired-reader observations remain preserved. Use the current
[local release report](LOCAL_RELEASE_REPORT.md) for source-bound HTTP evidence.

## Deployment boundary

The [deployment design](DEPLOYMENT_DESIGN.md) preserves the historical cloud-host
proposal outside the current release scope. No cloud resource or public inference
endpoint is created by this optimization. RecoLens continues to browse stored
outputs. [Local release verification](LOCAL_RELEASE_REPORT.md) separately measures
the indexed reader through HTTP under its fixed Windows workload and lifecycle.

The selected delivery uses [local inference and a static public illustration](LOCAL_DEMONSTRATION.md).
The local guide records the explicit indexed-reader launcher and separate HTTP
verification. Cloud hosting is outside the selected scope; package-reader memory
alone cannot substitute for HTTP or workload measurements. The earlier Linux
reader results retain their original outcomes.
