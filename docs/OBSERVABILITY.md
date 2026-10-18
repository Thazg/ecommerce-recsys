# Local service observability

## Scope

The [snapshot API](RECOMMENDATION_API.md) exports process-local metrics and
structured service events. Instrumentation covers the HTTP boundary, primary
worker, admission, optional [cache/fallback](SERVICE_CACHE_AND_FALLBACKS.md),
model identity and process memory. It preserves the locked model, snapshot
cutoff and recommendation schema 1.1.0.

The supported launcher enables owned JSON events on stderr. `GET /metrics`
exports Prometheus text 0.0.4 on the same loopback listener. It is an operational
endpoint outside the recommendation OpenAPI schema. No external collector,
dashboard, alert delivery or remote log store is installed.

```sh
python -m ecommerce_recsys.serving --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
curl http://127.0.0.1:8000/metrics
```

The model bundle is generated separately and remains outside Git. Startup
requires its complete inventory and trusted manifest pin. Metrics do not permit
serving an incomplete or incompatible bundle.

## Metric contract

Every application owns an independent registry. Counters and histogram buckets
are synchronized and cumulative for its lifetime; restarting creates a new
registry. Series appear when an event is first observed. Histogram bounds are
0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1 and 5 seconds, plus infinity.
No individual latency samples or request records are retained in the registry.

| Family | Type and dimensions | Meaning |
| :--- | :--- | :--- |
| `recsys_http_requests_total` | Counter: endpoint, method, status, outcome | One observation per HTTP invocation, including early validation failures |
| `recsys_http_errors_total` | Counter: fixed error code | Application error envelopes attributed at the boundary/handler |
| `recsys_http_duration_seconds` | Histogram: endpoint, outcome | ASGI receive/validation/handling through successful final-body send, or early termination |
| `recsys_deliveries_total` | Counter: route, cache, degraded | Successfully completed recommendation HTTP responses |
| `recsys_delivery_duration_seconds` | Histogram: route, cache, degraded | Successful recommendation boundary duration separated by delivery path |
| `recsys_admission_total` | Counter: decision | Accepted primary submissions, busy rejection, attempted busy fallback and not-ready rejection |
| `recsys_primary_calls_total` | Counter | Started primary worker calls; startup smoke excluded |
| `recsys_primary_duration_seconds` | Histogram: outcome | Worker computation, output validation and optional cache insertion; success, failed or invalidated |
| `recsys_primary_in_flight` | Gauge | Primary worker execution currently active; this is not a permit-availability flag |
| `recsys_cache_events_total` | Counter: event | Hits, misses, evictions, expirations and oversized insertions; retained after cache disable |
| `recsys_cache_entries`, `recsys_cache_charged_bytes` | Gauges | Retained cache inventory and accounting charge |
| `recsys_cache_enabled`, `recsys_cache_failures` | Gauges | Optional cache availability and recorded service cache failures |
| `recsys_cache_max_entries`, `recsys_cache_max_charged_bytes`, `recsys_cache_ttl_seconds` | Gauges | Operator configuration |
| `recsys_cache_sample_success`, `recsys_memory_sample_success` | Gauges | Whether the corresponding scrape sample succeeded |
| `recsys_process_resident_memory_bytes` | Gauge | Whole serving-process RSS at scrape time; excludes client/verifier processes |
| `recsys_ready`, `recsys_state` | Gauges; state enum on the latter | Current readiness and one-hot starting/ready/failed/stopped state |
| `recsys_model_info` | Gauge: version, manifest SHA-256 | One currently loaded model identity, cleared after resource cleanup |
| `recsys_startup_duration_seconds` | Gauge | Startup attempt including loading, smoke and any failure cleanup |
| `recsys_lifecycle_events_total` | Counter: fixed event | Startup outcome, resource cleanup and cache/primary/fallback/submission faults |
| `recsys_observer_errors_total` | Counter | Caught instrumentation, owned event-sink and scrape-sampling errors |

HTTP endpoints map to `recommendations`, `live`, `ready`, `openapi`, `docs` or
`other`. Unknown paths and methods share fixed buckets. Status dimensions use
200/400/404/405/413/415/422/500/503 or `other`. Outcomes are `completed`,
`cancelled`, `disconnected` or `aborted`. Routes and cache statuses are the fixed
response enums. Model version/manifest occur only on one information sample,
not on request counters or latency histograms.

User IDs, item IDs, request IDs, raw URLs, query strings and exception text are
never metric labels. Version replacement requires service restart; registry
state is not accumulated across model versions. `/metrics` requests are excluded
from HTTP counters/events to avoid scrape self-observation. Its own failure
returns 503 when export cannot complete.

## Timing and cancellation

HTTP histograms start before ASGI body parsing and end after the final response
body is accepted by `send`. They exclude pre-ASGI socket queues and do not
measure receipt by the client. The verifier's persistent loopback timings include
client request/response transfer and have a different boundary.

A cancelled HTTP waiter increments the cancelled outcome. Its already accepted
worker retains admission and can complete later; that completion is recorded in
the primary histogram independently. A successfully computed result whose HTTP
waiter was cancelled is not a completed delivery. Busy fallback attempts and
successful degraded deliveries are separate counters, so fallback failures
cannot appear as successful degraded responses.

Fast cache hits, busy rejections and validation failures have separate dimensions
from primary worker cost. Aggregating all outcomes into one latency percentile
can conceal slow primary inference. The histogram bounds provide approximate
quantiles after aggregation, not exact request-level p95 values.

## Structured events and privacy

The dedicated `ecommerce_recsys.serving.events` logger emits JSON objects with
event name, Unix timestamp and the trusted model version where available.
Completed/terminated HTTP events add server-generated request ID, fixed endpoint/
method/status/outcome, allowlisted error code where applicable, duration and
successful route/cache/degraded attribution. Worker/fallback/submission fault
events retain the server request ID when available; startup has no request ID.
The request ID is a log correlation field, never a metric label.

Owned events contain no input body, raw user/item ID, output list, raw path/query,
backend exception string or traceback. Fault events use fixed names such as
`primary_failed`, `fallback_failed` and `cache_disabled`. `cleanup_complete`
describes the shared worker drain for shutdown or failed/cancelled startup.
Each started lifecycle attempt records one startup outcome and duration. The
owned drain records failed, cancelled or `startup_stopped` outcomes after cleanup,
even if the caller is cancelled again. The first captured termination cause is
retained; stopping before readiness is distinct from a successful startup.
The launcher configures this logger only; package import does not change root
logging. Embedded applications must configure the dedicated logger themselves.

This guarantee applies to owned JSON events. Uvicorn diagnostics, Python warnings
and third-party model-library output are separate streams and are not certified
as redacted by this module. Uvicorn access logging remains disabled. Public log
collection requires an explicit review of every collected stream.

## Failure isolation and resource scope

Observer/event-sink exceptions are caught and counted. They do not change
recommendation success, readiness failure or permit ownership. A logging failure
can lose that event; there is no durable delivery, retry queue or audit-log SLA.
The local stderr handler is synchronous, so a slow sink can delay the event loop.

Scraping reads state without fitting/calling a model, acquiring numerical
admission, expiring cache entries or disabling a faulty cache. A failed cache or
RSS sample reports sample-success zero; the unavailable measurement is omitted.
Cache inventory samples must contain plain nonnegative integers within both
configured entry/charge limits. If either field is invalid, both inventory gauges
are omitted and sample-success is zero; the scrape leaves the cache unchanged.
Other inference paths keep their existing validation/failure policies.
Snapshots cover separate instants and are not a transactional view of all fields.

Cache charge excludes fixed container/allocator costs and is not an RSS cap.
Scrape RSS is a point sample, not peak memory or a capacity prediction. The
paired verifier separately samples process RSS every 50 ms; its sampled peak
remains a lower bound. The charter's 2 GiB memory target and workload-based
latency/reliability gates still require independent acceptance evidence.

## Example operational queries

With a separately configured Prometheus collector, examples are:

```promql
sum(rate(recsys_admission_total{decision="busy_rejected"}[5m]))
sum(rate(recsys_deliveries_total{degraded="true"}[5m]))
histogram_quantile(0.95, sum by (le) (rate(recsys_primary_duration_seconds_bucket{outcome="success"}[5m])))
recsys_process_resident_memory_bytes / 1024 / 1024 / 1024
```

Event series are created lazily; absent events produce absent series. An alert
must explicitly handle missing samples, scrape failures and restarts. These
examples do not constitute installed alerts or a demonstrated service objective.

## Verification evidence

The [source-pinned receipt](../benchmarks/serving/observability_lifecycle_validation_v1.json)
records two real loopback server processes using the unchanged fold-9 manifest
and 100 warm/one cold producer references. Off/miss/hit outputs, prefix calls
and canonical cold reuse match the same reference identity as earlier HTTP
receipts. No accuracy evaluation or policy selection is repeated.

| Process | Observed HTTP invocations | Completed recommendations | Owned JSON records | Metric samples at final scrape |
| :--- | ---: | ---: | ---: | ---: |
| Cache off | 106 | 102 | 107 | 105 |
| Cache on | 215 | 210 | 216 | 135 |

HTTP totals include health/schema requests; cache-off deliveries include one
excluded warm-up. The cache-on sequence includes 101 misses, 101 repeated hits,
six prefix and two canonical cold calls. Scrapes are excluded. One startup-ready
event accounts for the additional JSON record in each process. The verifier
checks unique samples, histogram bucket/count invariants, loaded model identity,
primary duration/call counts and cache counters. All reconcile with no observer
failures. Metric text and owned-event content hashes are retained in the receipt;
raw per-request logs remain outside Git.
Sample uniqueness and histogram matching use canonical label sets, so reordered
labels cannot disguise duplicate time series.

Client-measured warm HTTP timings on Windows/AMD64, Python 3.13.15:

| Path | Requests | p50 ms | p95 ms | p99 ms |
| :--- | ---: | ---: | ---: | ---: |
| Cache off | 100 | 101.30 | 241.85 | 519.14 |
| Cache on, miss | 100 | 88.81 | 231.69 | 293.84 |
| Cache on, hit | 100 | 1.29 | 1.85 | 2.20 |

Both prospective cache hit/miss ratio gates pass. These are client timings,
distinct from exported ASGI histograms. The two processes start independently;
no paired telemetry-on/off overhead claim follows. The constructed repeat sample
does not establish production hit rate, throughput, rejection rate or an SLA.
Uncached p99 in this sample exceeds the initial 500 ms charter target. The
latency ratio gates do not replace that independent performance budget.

| Process | Launch to ready s | Ready RSS GiB | After requests GiB | Sampled peak GiB |
| :--- | ---: | ---: | ---: | ---: |
| Cache off | 24.37 | 1.86 | 1.84 | 2.25 |
| Cache on | 24.00 | 2.18 | 2.18 | 2.40 |

**Cache-on ready RSS exceeds the 2 GiB loaded-memory target.** Both sampled
process peaks also exceed 2 GiB; cache-off ready RSS is below that threshold in
this run. No workload-wide memory compliance or model-memory optimization is
established. Hardware load, allocator behavior and filesystem caches vary
between runs; these measurements do not revise the budget or establish Linux
full-bundle parity.

Regression verification: 541 passed, one Windows symlink-privilege skip with
`pytest`. The 32 added observability cases cover thread-safe accounting,
independent registries, malformed/early exits, privacy sentinels, cancellation,
busy fallback, startup/cleanup, cache fault/expiry, RSS failure and actual owned
stream-write failure. Regression cases also enforce one startup outcome after
stop/repeated cancellation or executor failure, canonical label matching and
invalid cache-sample isolation. A fitted tiny ALS/KNN snapshot retains its existing HTTP
parity/fallback test. Forced failures are deterministic test evidence; the real
probe observes normal paths, not a failure/load campaign.

Reproduce with a new output path:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt
pytest
ruff check .
ruff format --check .
python scripts/verify_service_observability.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/observability_verification_repeat.json
```

The verifier refuses receipt overwrites, binds service/runner/helper/requirement
bytes and independently checks telemetry after the paired cache probe. Earlier
[observability](../benchmarks/serving/observability_validation_v1.json),
[cache](../benchmarks/serving/cache_validation_v1.json),
[state-hardening](../benchmarks/serving/cache_state_validation_v1.json) and
[HTTP boundary](../benchmarks/serving/http_boundary_v1.json) receipts retain their
original source identities. The disposable probe processes are terminated after
verification; graceful drain remains separately tested.

The exporter follows the official [Prometheus text exposition contract](https://prometheus.io/docs/instrumenting/exposition_formats/)
and [label naming/cardinality guidance](https://prometheus.io/docs/practices/naming/).
