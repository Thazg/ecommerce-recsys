# Local API input and exposure controls

## Supported boundary

The [snapshot API](RECOMMENDATION_API.md) uses a loopback-only, single-process
HTTP/1.1 launcher. API contract **1.2.0** adds bounded request admission,
absolute input deadlines, local Host/Origin checks and optional shared bearer
authentication. Recommendation bodies, model/policy identity, cache semantics
and the full seen-item filter retain their existing contracts.

These controls address malformed requests, slow input, local request bursts,
forwarded-header spoofing and unwanted browser origins. They do not establish
public deployment security, tenant/user authorization, TLS, a workload SLO or
resilience to a compromised host. A valid shared credential grants access to
any stored snapshot user. Public exposure requires a separate access and
deployment contract; enabling a token does not permit external binding.

## Fixed defaults and admission order

| Control | Default | Boundary |
| :--- | ---: | :--- |
| Open accepted TCP connections | 32 | Excess sockets close immediately, including incomplete-header clients |
| Header deadline | 5 s | Absolute first-request and subsequent idle/header phase; bytes do not renew it |
| Complete header budget | 16,384 bytes | Sum of `len(name) + len(value) + 4` per parsed field, plus final two bytes |
| Incomplete h11 event buffer | 16,384 bytes | Separate parser setting; not a complete-header guarantee |
| Raw request target | 8,192 bytes | Includes path and query; excludes method and HTTP version |
| Recommendation body | 8,192 bytes | Declared and actual bytes; oversized chunks are rejected before copying |
| Body deadline | 5 s | Entire ASGI body read, independent of the header deadline |
| Active body readers | 8 | No reader queue; slots release before JSON parsing/model admission |
| Global recommendation bucket | 10 requests/s, burst 20 | Attempts before credentials/body/cache/model |
| Socket-peer bucket | 5 requests/s, burst 10 | Actual peer, independent of requested user or forwarded headers |
| Peer table | 128 entries, 300 s idle expiry | Full table rejects new peers; active peers are not evicted for fresh bursts |
| Uvicorn concurrency / backlog / keep-alive | 32 / 64 / 5 s | Secondary server/OS settings, separate from numerical admission |

Header counts use h11's parsed fields, after its framing normalization. At the
ASGI boundary the same formula applies to received fields. It excludes the
request line; the raw target has its own limit. Parsing and transport reads can
temporarily allocate beyond these field budgets; this is not a byte-exact RSS
or kernel-queue limit. The socket cap closes excess accepted transports; it
does not prevent TCP establishment or bound the operating system's listen queue.

The narrow protocol adapter requires **Uvicorn 0.54.0 and h11 0.16.0** and fails
startup for an unaudited version. It reuses the parser rather than copying it.
A generation-checked timer is cancelled when a Request is parsed, and rearmed
when the connection awaits the next request. It does not time out an accepted
model computation or a body that is still within its separate deadline.
Slow numerical work remains non-preemptible.

For requests reaching ASGI, server request identity and telemetry wrap the
following checks:

1. Target/header bounds, exact local Host and optional same-origin Origin.
2. Atomic global/peer recommendation attempt admission, including cache hits.
3. Optional credentials and unambiguous framing/content encoding.
4. Bounded body readers, absolute deadline and existing strict JSON/schema.
5. Existing readiness, cache, one numerical permit and optional busy fallback.

Rate denial charges neither bucket partially. `Retry-After` is a positive
integer rounded up from the larger required refill; table overflow uses the
next peer-expiry interval. Unknown users share their socket peer's budget.
The global bucket also constrains clients using different loopback source IPs.
Health/metrics do not consume recommendation tokens or reader slots. They
remain subject to transport and access policy; socket exhaustion or blocking
stderr can still prevent a timely probe response.

The launcher fixes production defaults. Embedded applications may pass an
immutable, validated `SecuritySettings` with explicit local authorities. This
does not install the TCP guards: those require the supported launcher/protocol.
Rates must be at least 0.001/s, durations at least 0.01 s, with finite upper
bounds; integer budgets reject booleans and fractions. Peer expiry must cover
its full refill period. Policy changes require restart and new measured evidence.

## Host, Origin and framing

The launcher allows its bound loopback IP and `localhost`, with the configured
port. IPv6 authorities require brackets. No DNS lookup, wildcard, trailing-dot
alias, userinfo or forwarded authority is accepted. `proxy_headers=False`
prevents Uvicorn from replacing the actual socket peer or scheme from
`Forwarded`/`X-Forwarded-*`. Those headers grant no access or quota bypass.

Programmatic calls may omit Origin. A supplied Origin must be one exact,
well-formed HTTP origin matching the request's permitted Host authority;
`null`, foreign origins, duplicates and path/query/userinfo components fail.
Host/Origin checks constrain browser/exposure behavior and do not authenticate
a local caller. No wildcard CORS policy is installed.

Only canonical `POST /v1/recommendations` accepts a body. Unsupported routes,
methods and trailing-slash aliases cannot start an unbounded body stream or
redirect into inference. Duplicate/ambiguous framing fields reaching ASGI and
unsupported content encodings are rejected. h11 may reject or normalize
framing before dispatch. Early application rejection closes the connection
instead of draining unread input. Normal successful requests retain keep-alive.

Request trailers are unsupported. The adapter rejects a `Trailer` declaration
before ASGI dispatch and rejects nonempty trailers at `h11.EndOfMessage` before
the body reader can complete. This includes undeclared trailers and fields sent
after an ASGI reader has started. Ordinary chunked JSON with an empty trailer
section remains supported. Parsing may allocate trailer fields before rejection;
this policy is not a byte-exact transport-memory bound. Embedded ASGI can reject
the declaration, but actual trailer enforcement requires the supported protocol.

## Optional operator credential

Default operation is **local anonymous**. For bearer mode, provision one
cryptographically generated token through either `RECSYS_API_TOKEN` or
`RECSYS_API_TOKEN_FILE`, never both. For example, in the activated environment:

```powershell
$env:RECSYS_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
python -m ecommerce_recsys.serving --bundle-path artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
```

Protect the operator environment/secret file and avoid printing it into logs.
Clients send `Authorization: Bearer <token>`. Tokens contain 32–256 printable
non-whitespace ASCII bytes. A secret file may have one final LF/CRLF; reads
are bounded and interior controls fail. Format validation does not prove
entropy. Comparison is constant-time after strict single-header parsing.
There is no CLI secret-value option, query credential, token digest in receipts,
hot rotation, account system or per-user object access control.

Bearer mode protects recommendations, readiness, metrics, schema and unknown
routes. `/health/live` remains unauthenticated and reveals only its server
request ID, alive status and lifecycle state. Interactive `/docs` and `/redoc`
are disabled in bearer mode; authorized `/openapi.json` describes the HTTP
bearer scheme. Missing/wrong credentials share one generic 401 response.
`create_app()` callers configure credentials explicitly through
`SecuritySettings`; environment credential loading belongs to the launcher.

## Errors, metrics and privacy

| HTTP status | Code | Meaning |
| :--- | :--- | :--- |
| 400 | `invalid_host` / `invalid_request` | Invalid authority, target, framing or unsupported request body |
| 401 | `unauthorized` | Missing/invalid shared credential; `WWW-Authenticate: Bearer` |
| 403 | `forbidden_origin` | Origin fails the local same-origin policy |
| 408 | `body_timeout` | Absolute body-read deadline expired |
| 413 | `body_too_large` | Existing 8 KiB body limit |
| 429 | `rate_limited` | Global, peer or bounded-table admission rejected; `Retry-After` |
| 431 | `headers_too_large` | Complete ASGI fields exceed the budget |
| 503 | `request_overloaded` | No body-reader slot; separate from inference `busy`/`not_ready` |

Application responses retain server-generated correlation IDs and safe error
envelopes. They use `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`; no TLS/HSTS guarantee is implied. Input/access
denials do not mark the model failed or count as successful/degraded deliveries.

Protocol input-limit/invalid-HTTP errors can return plain 400 before ASGI;
header expiry and excess connections close without an application response.
They have no JSON/request-ID/application HTTP metric guarantee. The separate
`recsys_transport_events_total{event=...}` counter uses only `header_timeout`,
`connection_limit`, `input_limit`, `invalid_http` and `trailers_rejected`. Parsed header limits may
therefore produce pre-ASGI 400 or ASGI 431, depending on the entry point.
The `trailers_rejected` event counts unsupported trailer declarations
or trailer fields. A rejection after ASGI begins can also produce a disconnected
HTTP observation with no completed delivery; the protocol's plain 400 has no
application JSON/request-ID guarantee.

Owned [telemetry](OBSERVABILITY.md) keeps only finite status/error/event enums.
It does not record credentials, token hashes, socket IPs, payloads, raw targets,
headers or exception text. `/metrics` remains excluded from HTTP self-observation,
including its access denials. Uvicorn/model-library output retains a separate
logging boundary; synchronous owned stderr can block. No durable logging or
public security certification is claimed.

## Verification

The source-pinned [hardening receipt](../benchmarks/serving/hardening_boundary_validation_v1.json)
records the unchanged fold-9 manifest, reference component, numerical reader,
service/runner/requirement hashes, effective nonsecret policy and runtime.
It compares local-anonymous/cache-off with bearer/cache-on processes. Both use
default input/rate controls and pace normal recommendation attempts at 0.26 s
intervals; pacing delays are excluded from client request durations. Each call
uses a new loopback HTTP connection, unlike earlier persistent-connection probes.
Authentication and caching vary together, so their individual costs are not
isolated by this comparison.

All 100 warm/one cold references are checked on off/miss/hit paths, with six
prefix checks, two canonical-cold checks and one post-denial warm recovery per
process. The probe also checks invalid Host/Origin, encoding, oversized/malformed
bodies, complete-header/trailer rejection, default header/body deadlines, finite rate
bursts with spoofed forwarded identity and bearer operational endpoints. It
reconciles HTTP/model/delivery/transport counts and owned JSON events. Concurrent
reader/socket exhaustion, cancellation, pipelining, stale timers and a fitted
tiny snapshot's real TCP parity have separate automated coverage. Socket helpers
fail on premature EOF rather than spinning, shared content-encoding errors are
declared for health routes, and out-of-range integers fail configuration validation
before conversion to a finite float.

Reproduce from the receipt's matching source and pinned environment, choosing
a fresh output path:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt
python -m pip check
pytest
ruff check .
ruff format --check .
python scripts/verify_service_hardening.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/hardening_repeat.json
```

Earlier HTTP/cache/observability receipts retain their own source identities
and exact schema checks. Reproduce the pre-hardening observability implementation
from `d618394`; its 1.1.0 runner is not the current 1.2.0 verification command.
This work does not refit a model, repeat full-fold accuracy or certify Linux
full-bundle parity. The independent memory and latency budgets remain release
gates; protection and cache-ratio checks do not waive them.

### Measured result

The local implementation gate completed with `pytest`: **699 passed, one
Windows symlink-privilege skip**. `ruff check .`, `ruff format --check .` and
`python -m pip check` also pass. The current source/model receipt pins match;
all six earlier published serving receipts retain their original bytes.

On Windows/AMD64, Python 3.13.15, the 100-warm-reference client sample gives:

| Path | p50 ms | p95 ms | p99 ms |
| :--- | ---: | ---: | ---: |
| Anonymous, cache off | 92.14 | 240.77 | 266.71 |
| Bearer, first cache miss | 90.53 | 240.69 | 254.26 |
| Bearer, cache hit | 18.78 | 28.77 | 30.37 |

Both prospective cache ratio gates pass. The single cold reference is not a
latency distribution. These durations include a new TCP connection per request;
the earlier observability probe reused a persistent connection. A comparison
with its 1.85 ms hit p95 cannot isolate cache or security overhead. Neither
sample establishes a serving SLO or a representative cache hit rate.

| Process | Launch to ready s | Ready RSS GiB | After requests GiB | Sampled peak GiB |
| :--- | ---: | ---: | ---: | ---: |
| Anonymous, cache off | 19.98 | 2.20 | 2.20 | 2.42 |
| Bearer, cache on | 19.97 | 2.19 | 2.20 | 2.40 |

**Both ready RSS and sampled peaks exceed the 2 GiB charter budget.** Sampling
every 50 ms lower-bounds the true peak; separate processes and varying cache/
credential settings do not isolate allocation costs. The warm latency sample
falls below the initial 300/500 ms p95/p99 budgets in this run, while the earlier
observability sample missed p99. No workload-wide budget compliance follows.

Off/on counters reconcile **136/238 HTTP invocations**, **111/211 deliveries**,
**111/101 primary worker calls** and **137/239 owned JSON records**. Final
scrapes contain 135/181 samples and zero observer errors. Each process records
one input-limit event, one header-timeout event, one ASGI body timeout and five
denied attempts in its finite 15-request burst. Two `trailers_rejected` events
cover the pre-ASGI declaration and the undeclared trailer after a 100-continue
handshake. The latter has one disconnected HTTP observation and no delivery.
Oversized incomplete trailers may instead fail earlier through h11's parser
limit and count as `invalid_http`. Bearer-denied metrics are deliberately excluded
from HTTP self-observation. The enabled cache retains 101 entries, 217,152
charged bytes, 101 misses and 110 hits within its limits.
