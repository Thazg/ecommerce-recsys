# Snapshot HTTP capacity assessment

## Scope

This assessment measures the unchanged snapshot service on the qualified
Linux/amd64 Docker Desktop image. It exercises a finite constructed HTTP
workload, rather than observing production traffic or changing recommendation
quality. The original model, API, cache defaults and security quotas are preserved.
Public deployment and online evaluation remain unimplemented.

The [completed receipt](../benchmarks/performance/http_capacity_boundary_validation_v1.json)
binds the model manifest, image, upstream qualification, release controller,
workload policy, source and host/container resources. The [runner](../scripts/benchmark_http_capacity.py)
and [driver](../scripts/http_capacity_workload.py) implement the declared grid.
The [initial receipt](../benchmarks/performance/http_capacity_validation_v1.json)
is preserved with its original source identity. The current receipt repeats the
same prospective grid after checkpoint validation was strengthened; the tables
below describe this repeat, rather than combining independent runs.

## Prospective policy

The workload policy was fixed before measurement. Each cell gets a fresh process
and container, 2 CPUs, a 4 GiB memory/swap cap, read-only root/model, numeric UID,
dropped capabilities, no external network and no published ports. No quota or
admission setting is raised. Requests use anonymous loopback mode; bearer-auth
overhead is outside this workload. The unchanged model was not refitted or optimized.

| Cell | Offered rate | Client inflight bound | Cache |
| :--- | ---: | ---: | :--- |
| Uncached control | 1 request/s | 4 | Off |
| Uncached offered load | 4 requests/s | 8 | Off |
| Primed-cache control | 4 requests/s | 8 | On |
| Primed-cache quota stress | 8 requests/s | 16 | On |

Every cell measures 150 seconds, with deterministic open-loop arrivals and no
retries. When the client inflight limit is reached, the arrival is counted as
client shedding; it never disappears into a growing client queue. Completed
throughput uses actual elapsed time including drain. Scheduling lateness and
schedule-to-completion latency are recorded separately from client HTTP-call
latency, which includes parsing and response validation.

Reference order rotates deterministically by 42; it is not random population sampling.
The fixed population contains 100 sealed warm reference users and one explicit
cold context. Requests use 0.8 warm/0.2 cold and K=20/10/5 fractions 0.6/0.2/0.2.
All six cohort/K combinations occur. The matched 4-request/s controls use the
same complete request-sequence digest. Repetition over these contexts is an
assumption; this sample does not establish behavior over the full user population.

Before each workload, all 101 references are checked at K=20 with at least 0.26 s
spacing between calls, followed by a 3 s settling interval. This also primes the
optional cache. The cache cells use 256 entries, 1 MiB charged-entry budget and 900 s
TTL, avoiding expiry during a cell. Their hit rate represents a deliberately
primed repeated-workload scenario, not measured production cacheability. Cache
remains off by default; fallback remains disabled by busy_policy=reject.

The single-peer quota remains 5 requests/s with burst 10; the global quota remains
10 requests/s with burst 20. The 8-request/s cell intentionally exceeds the peer
refill rate. HTTP 429 quota rejections and HTTP 503 worker-busy responses have separate counters.

## Response and measurement integrity

Every successful response is checked against the sealed reference Top-K IDs,
route, cutoff, bundle version, manifest, request-ID correlation/freshness and
security headers. After the measured window, all 101 references are checked again.
Client POST outcomes reconcile exactly with service POST/delivery/primary/cache/
busy/rate counters; transport failures or unreconciled evidence prevent successful
publication. The receipt requires complete parity, telemetry and cleanup verification.

Serving PID 1 RSS/CPU use a nominal 50 ms sampling interval during workload and
drain. Ready RSS,
after-priming RSS, sample coverage/gaps, CPU deltas, driver CPU/RSS and cgroup
peak are separate fields. Cgroup peak includes both driver and service and may
include startup/reference phases; it is not serving-process RSS. The driver runs
in the same cgroup and uses internal loopback, so these are colocated-client
measurements without external-network or native-host qualification.

The fixed targets retain warm-success HTTP p95 ≤ 300 ms, p99 ≤ 500 ms and serving
RSS ≤ 2 GiB. A cell needs at least 100 warm successes, error fraction ≤ 0.01,
rejection+client-shed fraction ≤ 0.01 and dispatch p99 ≤ 10 ms to classify a supported
rate in this grid. Successful warm/cold and hit/miss/disabled timings remain
separate; fast rejections do not enter success latency. Passing one cell would
not establish a universal maximum throughput, statistical SLO or deployment gate.

## Results

| Workload | Arrivals | HTTP 200 | HTTP 503 | HTTP 429 | Client shed | Warm successes | Warm p95 (ms) | Warm p99 (ms) | Serving RSS max (GiB) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| uncached-1rps | 150 | 150 | 0 | 0 | 0 | 120 | 226.097 | 413.657 | 2.264 |
| uncached-4rps | 600 | 584 | 16 | 0 | 0 | 468 | 225.597 | 343.248 | 2.263 |
| primed-cache-4rps | 600 | 600 | 0 | 0 | 0 | 480 | 5.211 | 6.067 | 2.263 |
| primed-cache-8rps | 1200 | 759 | 0 | 441 | 0 | 606 | 5.369 | 5.757 | 2.263 |

| Workload | Successful requests/s including drain | Rejection fraction of arrivals | Dispatch p99 (ms) | RSS/CPU samples | Max sampling gap (ms) | Serving CPU (s) | Cgroup peak (GiB) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| uncached-1rps | 1.0000 | 0.000000 | 0.795 | 2976 | 52.257 | 11.380 | 2.379 |
| uncached-4rps | 3.8933 | 0.026667 | 0.791 | 2977 | 57.761 | 44.560 | 2.378 |
| primed-cache-4rps | 4.0000 | 0.000000 | 0.872 | 2975 | 51.610 | 1.570 | 2.380 |
| primed-cache-8rps | 5.0599 | 0.367500 | 0.854 | 2976 | 51.844 | 2.580 | 2.378 |

All four cells completed exact response/reference parity, telemetry reconciliation
and one graceful cleanup event with confirmed container removal. This includes
2,550 measured arrivals and 808 separately paced pre/post reference checks. No
transport errors or client shedding occurred. Both uncached cells passed the
successful-warm latency targets, but every cell exceeded the 2 GiB RSS budget.
No tested point satisfies all declared resource/performance gates.

The uncached 4-request/s repeat also fails the rejection gate: 16/600
arrivals returned worker-busy 503 (fraction 0.026667, above 0.01). The
primed 8-request/s cell fails that gate through quota rejections. Timing and busy
counts vary between independent runs; differences from the preserved initial
receipt are not evidence of an optimization or a supported 4-request/s rate.

The paired 4-request/s cells use identical request-sequence hashes. Primed
hits measure bounded result reuse, not faster model computation. The 8-request/s
cell reports single-peer quota rejections explicitly; it does not establish
model saturation or a new supported offered rate. Cold timings remain separate
in the receipt. Repeated arrivals still cover only 100 distinct warm contexts.

Validation passed 1,011 Windows unit tests plus 9 fitted-process cases (one allowed
symlink skip), and 1,012 Linux unit plus 9 fitted-process cases (no skips). The 68
capacity cases are included in these totals. Fixture CI is separate from
the real-model workload. Reproduce with `pytest tests/unit` and
`pytest tests/integration -m "not real_bundle"`, then run the explicit capacity
command below. Private JUnit/logs and model components remain outside Git.

## Reproduction and checkpoints

Use ecommerce-recsys Python 3.13 with the original producer libraries, complete
sealed fold-9 bundle, unchanged qualified image and Docker Desktop Linux. Keep
adequate host RAM; an independent process/client shares the container cap.

```powershell
python scripts/benchmark_http_capacity.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --work-root .local/http-capacity-repeat --output .local/http-capacity-repeat.json
```

Use both a fresh work root and output path for an independent repeat; reuse a
work root only to resume matching checkpoints. The private work root stores source/policy/model/image/
machine-bound checkpoints, logs and owned-container journals. A checkpoint is
saved only after validated output, telemetry and graceful removal. Both live
collection and resume reconcile telemetry with outcome/cache counts, derive
throughput from counts and elapsed time, and require resource coverage across
the measured window. A valid checksum alone is insufficient. The fixed schedule
rejects unsupported warm/K policy mixes before collection or resume. Resume only
the same frozen inputs and resources; never edit hashes. An unresolved ownership
journal stops new work until the exact owned container is inspected/cleaned.
Do not remove a store or move its source while an instance remains owned. This
is checkpointed assessment, not a native-host disaster-recovery procedure.

## Interpretation and remaining gates

Assessment completion means the fixed workload and integrity checks finished;
it is distinct from meeting performance/resource targets. A 4 GiB cap does not
revise the 2 GiB RSS budget. No model/service optimization or production cache
adoption is claimed. These short finite cells do not replace sustained/burst,
resource-pressure, failure/recovery and native target-host validation in the
[roadmap](ROADMAP.md). Deployment eligibility remains false.

The model's existing folds 5–9 remain post-selection diagnostics, not blind
validation. HTTP parity checks do not add accuracy or business-impact evidence.
