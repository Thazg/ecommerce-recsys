# Snapshot recommendation API

## Scope

The local HTTP API serves the unchanged, immutable
[offline reference](MODEL_POLICY_REPORT.md) through the
[snapshot loader](MODEL_ARTIFACTS.md). It performs no training or dataset reads.
Known training users use full-hybrid candidates and learned ordering; unknown,
null or omitted user IDs use recent popularity. The cold route is a selected
model policy, not a recovery mechanism for inference errors.

API schema **1.2.0** adds [local input and exposure controls](API_HARDENING.md),
including optional shared bearer credentials. Schema 1.1.0 introduced bounded
result caching and an explicit overload-only fallback. Both remain disabled by default. Their configuration,
identity and evidence are documented in [cache and fallbacks](SERVICE_CACHE_AND_FALLBACKS.md).
The [observability contract](OBSERVABILITY.md) defines `GET /metrics`, owned
JSON events, bounded labels and HTTP/worker timing scopes.

The snapshot cutoff is **1441216678608** (2015-09-02 17:57:58.608 UTC).
A known ID selects its stored history and features at that cutoff. Requests
cannot provide new events, change the model or choose another candidate budget.
This historical snapshot demonstrates an inference boundary; it does not
provide current product availability or online accuracy evidence.

## Run locally

Use the existing `ecommerce-recsys` environment, Python 3.13, from the repository
root. In a new environment, install the project and optional HTTP dependencies:

```sh
python -m pip install -e ".[dev]" -r requirements/serving.txt
python -m pip check
```

The fitted bundle is not distributed through Git. Build and verify it following
the [artifact contract](MODEL_ARTIFACTS.md), using matching data and provenance.
For the published fold-9 manifest, run:

```sh
python -m ecommerce_recsys.serving --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
```

The default address is `http://127.0.0.1:8000`. `--host` accepts a loopback IP
or `localhost`; wildcard, external and other hostname bindings are rejected.
`--port` accepts 1–65535, subject to operating-system permissions.
`RECSYS_BUNDLE_PATH` and `RECSYS_MANIFEST_SHA256` can supply the two
model settings instead. The manifest pin must come from trusted evidence;
calculating a digest from an untrusted download does not authenticate it.
Never replace a recorded digest to bypass a failed compatibility check.

Use the supported single-process launcher, without reload or extra workers.
Every process would otherwise duplicate a large model state. The optional
shared bearer credential provides no per-user authorization, TLS termination
or public-hosting contract; the tested setup is loopback only. The default is
local anonymous access. See [credential provisioning](API_HARDENING.md#optional-operator-credential)
for `RECSYS_API_TOKEN` / `RECSYS_API_TOKEN_FILE`. Interactive documentation is
available at `/docs` in anonymous mode and disabled in bearer mode; authorized
clients can read `/openapi.json`.

To opt into caching and the prepared overload fallback, add
`--cache-max-entries 256`, `--cache-max-bytes 1048576`, `--cache-ttl-seconds 300`
and `--busy-policy recent_popularity` to the launch command. These are operator
settings; request bodies cannot override them. The default entry limit is zero
and the default busy policy is `reject`.

## Request and response

### `POST /v1/recommendations`

Send `application/json`, UTF-8, at most **8,192 body bytes**. Query parameters
are rejected. The body must be an object with only these fields:

| Field | Contract | Default |
| :--- | :--- | :--- |
| `user_id` | Opaque string of 1–128 characters, or null; whitespace-only IDs and ASCII control characters are rejected | null, explicit cold route |
| `k` | Strict JSON integer from 1 through 20; booleans, floating-point values and strings are rejected | 20 |

Numeric IDs must be supplied as strings. IDs are not trimmed or otherwise
coerced. Extra fields, including `history`, filters and model overrides, fail
validation. Duplicate object keys and nonfinite JSON numbers are rejected.

The service entry point also validates these fields for direct Python calls.
Invalid direct inputs raise a validation error before model admission and do
not mark a healthy model failed.

Example using Python's standard library:

```python
import json
from urllib.request import Request, urlopen

request = Request(
    "http://127.0.0.1:8000/v1/recommendations",
    data=json.dumps({"user_id": "643908", "k": 5}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=30) as response:
    result = json.load(response)
    print(result["items"], result["route"], result["bundle_version"])
```

The response contains `request_id`, ordered `items`, `route`, `bundle_version`,
`cutoff`, `manifest_sha256`, `cache_status`, `degraded` and `degraded_reason`.
Primary routes are `hybrid_learned` and `recent_popularity`. An explicitly
enabled busy fallback uses `recent_popularity_fallback`, `degraded: true` and
`degraded_reason: "busy"`. Cache status is `disabled`, `miss`, `hit` or `bypass`.
Cached results preserve primary prefixes and carry fresh request IDs. Results contain
up to `k` unique, catalog-eligible items and exclude the complete stored seen
set. Short or empty eligible outputs are valid. For the same route and snapshot
context, a Top-5 request matches the first five Top-20 items. A busy fallback
uses its declared popularity order and can differ from the primary route.
The server generates a fresh request ID and returns it in both the JSON
response and `X-Request-ID`; it does not trust a caller-supplied request ID.

### Health endpoints

| Endpoint | Successful meaning | Failure behavior |
| :--- | :--- | :--- |
| `GET /health/live` | Event loop answers HTTP; status `alive` | Does not certify model health |
| `GET /health/ready` | State `ready`, verified model loaded and startup predictions passed | 503 with `not_ready` after a model failure or during application shutdown |

`GET /metrics` is a separate local operational endpoint in Prometheus text
format. Scrapes do not call the model or participate in inference admission;
they remain available when the primary is busy or failed. A sampling failure
is marked explicitly and does not certify model health.

Readiness includes the bundle version and cutoff only when ready. Liveness
is independent of cache health. Readiness also reports aggregate cache state,
entry accounting, primary-call counts and fallback-call counts. A cache failure
disables that optional optimization while a healthy primary remains ready. Liveness
continues to return 200 after an inference failure. Startup uses
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/); Uvicorn starts
accepting connections after loading completes. A bad bundle or pin aborts
startup instead of opening an uninitialized service.
Overlapping startup/shutdown cannot publish readiness after shutdown starts;
startup cancellation and shutdown share cleanup until the loading worker exits.

## Execution and errors

One dedicated worker executes model calls outside the ASGI event loop. A
process-wide admission permit allows **one active model call and no application
inference queue**. A valid cache hit can answer while inference is busy. A cache
miss or disabled cache receives 503 `busy`, with `Retry-After: 1`, on overlap
under the default policy. Opting into `recent_popularity` instead returns an
attributed, seen-filtered recommendation from the prepared recent Top-1,000
pool. Degraded results do not populate the primary cache. Health requests can
still run. A ready service can be busy.
This is bounded admission, not a throughput or concurrent-load guarantee.

Cancelling an HTTP waiter does not interrupt model computation or release its
permit early. Only the worker releases admission after execution. Graceful
shutdown stops admission and waits for accepted work before dropping the model.
There is no inference deadline or thread preemption; a stuck computation can
therefore delay shutdown. Concurrent direct use of the underlying Python
bundle outside this service is unsupported because numerical thread controls
affect the entire process.

Unexpected inference failures or malformed backend outputs mark the service
failed. That request receives a generic 500; later recommendation requests
receive 503 until restart. No error is converted into a cold-policy success.
Snapshot-dependent fallback failures follow the same failure transition and
invalidate cached/prepared output without releasing another worker's permit.
An accepted primary still running when fallback invalidates the service returns
503 on completion. Admission rechecks readiness after acquiring the permit.
Server logs retain diagnostic exceptions; client errors omit raw inputs,
filesystem paths and tracebacks. Uvicorn access logging is disabled by default.

| HTTP status | Application error code | Meaning |
| :--- | :--- | :--- |
| 400 | `invalid_json` / `invalid_request` | Malformed UTF-8/JSON, duplicate keys, nonfinite numbers or invalid application-level length |
| 400 / 403 | `invalid_host` / `forbidden_origin` | Configured local authority or same-origin policy failed |
| 401 | `unauthorized` | Shared credential missing/invalid; `WWW-Authenticate: Bearer` |
| 408 | `body_timeout` | Absolute body-read deadline expired |
| 413 | `body_too_large` | Body exceeds 8 KiB, including chunked/no-length requests |
| 415 | `unsupported_media_type` | Expected `application/json` without unsupported content encoding |
| 422 | `validation_error` | Invalid schema, unsupported fields or query parameters |
| 429 | `rate_limited` | Recommendation rate/table budget exhausted; positive `Retry-After` |
| 431 | `headers_too_large` | Complete ASGI header budget exceeded |
| 500 | `inference_failed` / `internal_error` | Unexpected execution failure; no recovery recommendation |
| 503 | `busy` / `not_ready` / `request_overloaded` | Numerical admission, readiness or body-reader budget rejected |

Errors have the shape `{"request_id": "...", "error": {"code": "...",
"message": "...", "fields": []}}`. Unknown endpoints and methods use 404/405
`http_error`; OpenAPI declares these shared errors on registered operations.
Readiness uses its health schema. Malformed HTTP framing rejected
by Uvicorn before ASGI is outside the application's JSON-envelope contract.
The [hardening contract](API_HARDENING.md) defines separate 5-second header/body
deadlines, 32 accepted connections, eight body readers and bounded global/peer
rate admission. Protocol rejections can close the socket or return plain 400
before ASGI. These protections do not establish a serving SLA.

## Verification evidence

The historical [HTTP boundary receipt](../benchmarks/serving/http_boundary_v1.json) binds the original
manifest and reference component, unchanged reader fingerprint, API source and
requirement-file hashes, OpenAPI schema and measured runtime versions.
The verifier starts a separate server process without loading the model into
its parent. All **100 warm and 1 cold reference outputs** match at 20 items;
six warm prefix checks, one unknown-user cold check and seven error-contract
checks also pass. The receipt covers output parity, not a repeat of full-fold
quality scoring. The [original loaded-quality receipt](../benchmarks/artifacts/fold09_v1.json)
retains that separate evidence.

The [initial HTTP receipt](../benchmarks/serving/http_snapshot_v1.json) preserves
the earlier source identity and measurements. The boundary receipt verifies
the launcher, parsing guards, service validation and OpenAPI 1.0.0 contract
at Git revision `dc218a8`;
both use the same unchanged model bundle and reference outputs.

Measured on Windows/AMD64, Python 3.13.15, with one excluded warm-up and a
single persistent loopback HTTP connection:

| Measurement | Observed value | Scope |
| :--- | ---: | :--- |
| Launch to HTTP readiness | 20.61 s | Includes component verification, restoration and two startup predictions; cache state uncontrolled |
| Warm HTTP p50 / p95 / p99 | 74.35 / 231.36 / 303.02 ms | 100 sequential reference requests, including response-body transfer |
| Cold HTTP request | 13.00 ms | One reference, insufficient for a latency distribution |
| Server RSS when ready | 2.19 GiB | Whole server process, excluding verifier parent |
| Sampled peak server RSS | 2.42 GiB | Sampled every 50 ms; lower bound on the true peak |

The **2 GiB charter memory target is not met**: ready RSS is 2,352,865,280
bytes. The sampled peak is 2,593,103,872 bytes. The warm sample falls below the
charter's 300/500 ms p95/p99 goals, but it is not a workload/load test and does
not establish those service objectives. These HTTP timings must not be equated
with earlier source-only or offline inference timings.

For the pre-observability schema 1.1.0 cache-off/cache-on evidence, see the
[paired HTTP receipt](../benchmarks/serving/cache_state_validation_v1.json) and
[cache report](SERVICE_CACHE_AND_FALLBACKS.md). The pre-hardening observability
receipt retains its 1.1.0 source; current verification is described in the
[hardening report](API_HARDENING.md). Reproduce the boundary receipt's
1.0.0 contract from revision `dc218a8`; its runner compares that exact response
shape and cannot verify later operational contracts. Run current checks with:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt
pytest
ruff check .
ruff format --check .
python scripts/verify_service_hardening.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/hardening_repeat.json
```

The verifier refuses to overwrite completed receipts. Its disposable process
is terminated after the probe; deterministic unit tests separately verify
graceful drain, cancellation retaining admission, health responsiveness,
cross-instance admission and failure cleanup. New measurements can vary with
hardware, caches and runtime; preserve the original receipt.

Service tests are optional in a core-only installation and report that skip
explicitly. Once HTTP dependencies are installed, a missing declared test client
fails collection. CI imports FastAPI, Uvicorn and HTTPX2 explicitly before tests
so absent service dependencies cannot silently remove API coverage. Concurrency
tests coordinate a blocked worker with events; generous deadlines detect hangs
without treating scheduler speed as a latency benchmark.

## Limits

The API has no dynamic-history updates, stale-result recovery, automatic model
recovery, hot replacement, per-user authorization or public deployment. The optional
fallback handles busy admission only; failed inference still requires restart.
The later [Linux qualification](LINUX_CONTAINER.md) checks the full Windows-built
bundle in an isolated Linux container, with its separately declared numerical
policy; API fixture tests alone do not establish that compatibility.
The heavy snapshot restoration and process
memory need further engineering before a resource-budgeted deployment.
Previously inspected folds remain post-selection diagnostics, not blind
validation; adding HTTP does not improve or reconfirm model accuracy.
