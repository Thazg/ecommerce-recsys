# Snapshot cache and overload fallback

## Scope and defaults

The [HTTP API](RECOMMENDATION_API.md) supports an optional process-local result
cache and an optional overload fallback. The fitted model, training cutoff and
normal warm/cold policies remain the immutable [snapshot reference](MODEL_ARTIFACTS.md).
Neither feature uses request-time events or retrains a model.

Defaults retain uncached primary inference and 503 rejection when busy:

| Operator setting | Default | Contract |
| :--- | ---: | :--- |
| `--cache-max-entries` | 0 | Nonnegative integer; zero disables caching |
| `--cache-max-bytes` | 1048576 | Positive integer; budget for charged stored entries |
| `--cache-ttl-seconds` | 300 | Finite positive insertion TTL on a monotonic clock |
| `--busy-policy` | `reject` | `reject` or explicit `recent_popularity` |

The measured optional configuration uses 256 entries, 1 MiB entry charge and
300 seconds. These fixed values demonstrate bounded reuse; no real traffic
distribution or cache-size optimum has been established. The cache remains
opt-in. No Redis, remote dependency or persistent cache is introduced.

Example, after preparing the verified bundle and installing the
[HTTP requirements](../requirements/serving.txt):

```sh
python -m ecommerce_recsys.serving --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --cache-max-entries 256 --cache-max-bytes 1048576 --cache-ttl-seconds 300 --busy-policy recent_popularity
```

The launcher remains single-process and loopback-only. Request bodies still
accept only `user_id` and strict integer `k` from 1 through 20. Cache and busy
policy are operator settings, with no per-request overrides.

## Cache identity, expiry and accounting

The cache namespace binds the trusted manifest digest, frozen snapshot policy
and canonical Top-20 output semantics. Known IDs get separate keys. All unknown
and null IDs share the same empty-history cold context. The manifest binds the
stored history, catalog, model and feature state, so a snapshot replacement
cannot reuse another version's entries. Restart creates an empty instance;
hot replacement and dynamic histories remain unsupported.

Each entry stores an immutable validated Top-20 recommendation without request
metadata. A smaller K reads its exact prefix. Every hit gets a fresh request ID,
and metadata, catalog membership and full seen filtering are checked again.
Short and empty eligible results can be cached; results are never padded.

Hits update LRU recency but do not extend TTL. An entry expires at its insertion
deadline, including equality. Cache operations remove expired entries; writes
evict least-recently-used entries until both count and byte-charge limits hold.
Oversized entries are not stored. TTL reflects result-retention policy, not
freshness relative to real-world inventory or the historical data cutoff.

The byte charge includes shallow sizes of key/value objects, tuples and string
contents plus an entry reserve. Shared strings are conservatively counted per
entry. Fixed container, allocator and whole-process costs are excluded.
**This accounting budget is not an RSS cap.** Process RSS is measured separately.
Aggregate readiness counters describe the current cache instance; disabled
caches report zero live entries/counters and a separate failure count.

## Request paths and failure behavior

Input validation and readiness precede all cache/fallback decisions. A hit can
answer while another model call runs. A miss enters the original process-wide
numerical admission gate: one active worker, no inference queue. Concurrent
misses are rejected or take the opted-in fallback; they are not coalesced into
a waiting group. Cancellation leaves accepted computation running with its
permit until completion, and a healthy completed result may populate the cache.
Shutdown stops admission/hits/fallback, drains accepted work and drops cache
and prepared-pool state.

Admission rechecks readiness after acquiring the numerical permit, so a worker
failure during cache lookup cannot admit a new model call. Startup failure,
cancellation and shutdown share an owned cleanup task that drains the worker
before dropping resources. Startup cannot publish readiness after shutdown begins.

| Condition | Behavior |
| :--- | :--- |
| Cache hit, primary healthy | Return exact primary output prefix with `cache_status: "hit"` |
| Cache miss, primary available | Run primary; validate/cache its full Top-20, return requested prefix |
| Cache disabled | Run original primary path with `cache_status: "disabled"` |
| Cache operation or cached-value contract fails | Disable cache, record failure, bypass to healthy primary; no automatic cache recovery |
| Primary busy, default policy | 503 `busy` with `Retry-After: 1` |
| Primary busy, explicit recent policy | Return a seen-filtered prepared-pool result with degraded attribution |
| Primary inference/output fails | 500 for that request, discard cache, then 503 until restart |
| Prepared fallback context/output fails | 500 `inference_failed`, discard cache/pool and require restart; retain the active primary worker's permit until it finishes |
| Missing/corrupt bundle or failed startup | Abort startup; no unverified recommendations |
| Failed/stopped service | 503; cached and degraded responses are unavailable |

The busy fallback prepares up to 1,000 recent-popularity IDs from the verified
snapshot's existing direct source at startup, under numerical admission. It
preserves that source order and validates unique catalog membership. On busy,
it filters the user's **complete stored seen set**, then returns up to K items
without calling a model. It does not refill from below the prepared Top-1,000;
short/empty output is valid when that bounded pool is exhausted. This can have
lower availability than querying a full source after user-specific filtering.

Fallback results carry `route: "recent_popularity_fallback"`, `degraded: true`,
`degraded_reason: "busy"` and `cache_status: "bypass"`. All successful responses
include `manifest_sha256`, bundle version and cutoff. Normal cold routing keeps
`recent_popularity` and `degraded: false`. Degraded output never enters the
personalized primary cache. Warm fallback quality has not been evaluated as a
replacement for learned ordering; this is an explicitly exposed availability
trade-off, not a newly selected recommendation model.

Readiness means the primary snapshot is healthy. A busy primary or disabled
cache can remain ready. The probe exposes bounded aggregate cache information,
primary call counts and fallback counts; it exposes no per-user keys. Cache
failures do not hide primary failures, and no stale-result recovery, inference
timeout, thread preemption or automatic model recovery is implemented.
The [observability exporter](OBSERVABILITY.md) additionally retains cumulative
cache event counters after disable. Its inventory gauges include retained
expired entries until a normal cache read/write removes them; scrapes do not
change expiry or eviction behavior.
If a fallback failure invalidates the service during an accepted primary call,
that call also returns 503 rather than delivering a successful result from a
failed service. Liveness remains available.

## Paired HTTP evidence

The [cache validation receipt](../benchmarks/serving/cache_state_validation_v1.json) binds
the pre-observability API/runner/helper/requirements hashes, original model manifest and
reference hashes, schema, settings and runtime. Two separate server processes
use the same frozen 100 warm and one cold producer references on Windows/AMD64,
Python 3.13.15. The parent never loads the model. All output/lineage comparisons
pass for cache off, first miss and repeated hit, plus six prefix calls and two
canonical cold-context reuse calls.
The [observability report](OBSERVABILITY.md) records current service evidence;
the earlier cache receipts preserve their original source identities.

The fixed gate requires hit p95 at most 0.5 times uncached warm p95 and miss
p95 at most 1.25 times it, with exact reference output and bounded accounting.
Both latency gates pass. The experiment does not select configurations using
new accuracy results.

| Warm HTTP path | Requests | p50 ms | p95 ms | p99 ms |
| :--- | ---: | ---: | ---: | ---: |
| Cache off | 100 | 75.68 | 236.69 | 259.84 |
| Cache on, first miss | 100 | 82.26 | 221.35 | 300.40 |
| Cache on, repeated hit | 100 | 0.85 | 1.15 | 1.43 |

Timings include a persistent loopback HTTP request and response-body read.
Cache off has one excluded warm-up; cache on starts empty. Repeated hits make
zero additional primary calls: the count remains 101 after the second pass.
After prefix/cold checks the cache reports 101 entries, 109 hits, 101 misses and
**217,152 charged bytes**, with no eviction, expiration, oversize or failure in
this sequence. Cold timings have one reference per path and cannot establish a
latency distribution. This constructed repeat workload does not estimate a
production hit rate, throughput, admission rejection rate or service objective.

| Server process | Ready RSS GiB | After requests GiB | Sampled peak GiB | Launch to ready s |
| :--- | ---: | ---: | ---: | ---: |
| Cache off | 1.80 | 1.80 | 1.93 | 26.72 |
| Cache on | 1.87 | 2.02 | 2.03 | 21.80 |

**The cache-on process exceeds the charter's 2 GiB memory target.** The cache-off
samples stay below it in this run; this does not establish memory-budget
compliance across workloads. RSS is sampled at 50 ms, so the peak is a lower
bound. Independent processes, allocator behavior and filesystem cache state
prevent attributing the RSS difference to caching. Earlier runs exceeded the
target in both processes; no model-memory optimization is part of this change.

Deterministic tests cover insertion-TTL boundaries, LRU/count/charge limits,
immutable values, namespace/context isolation, concurrent operations, corrupt
cache data, dependency failures, fresh IDs, empty results, busy hit/miss paths,
cancellation, failure invalidation and shutdown. A tiny actually fitted ALS/KNN
snapshot verifies HTTP prefix parity and fallback equality with its real direct
source after full seen filtering. Forced busy/failure cases are test evidence;
the sequential real-bundle HTTP probe does not force those conditions.
Event-controlled regressions also cover failure during cache lookup, overlapping
startup/shutdown, repeated startup cancellation and fallback faults while a
primary worker owns admission.

Reproduce with a fresh receipt path:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt
pytest
ruff check .
ruff format --check .
python scripts/verify_service_cache.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/cache_verification_repeat.json
```

The verifier refuses receipt overwrites and terminates its disposable processes
after checking; graceful drain is separately covered by tests. The earlier
[cache receipt](../benchmarks/serving/cache_validation_v1.json) preserves the
implementation before admission/lifecycle/fallback failure hardening; its source
identity differs from the state-hardening receipt. Earlier
[snapshot](../benchmarks/serving/http_snapshot_v1.json) and
[boundary](../benchmarks/serving/http_boundary_v1.json) receipts retain their
original source identities. The snapshot and its M14–M15 accuracy evidence are
unchanged. Linux full-bundle parity, public deployment and representative load/
failure objectives remain separate release gates.
