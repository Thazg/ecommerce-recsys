# Local backend release verification

## Scope

The selected release runs the complete Retailrocket snapshot on an operator's
machine through the explicit indexed-reader launcher. The API stays on loopback.
Public RecoLens and RecoMe are independent static demonstrations; neither calls
this API. [ADR-40](DECISIONS.md#adr-40--define-a-local-backend-release-with-public-static-demonstrations)
defines the release boundary.

This assessment qualifies a fixed local workload and process lifecycle. It does
not train a model, change recommendation policy, replace the default package
loader, expose a public API or establish an availability SLA. Earlier Linux
container/load receipts retain their original reader, timings and memory failures.

## Prospective profile

The measurement policy is fixed in
[`scripts/verify_local_release.py`](../scripts/verify_local_release.py).
The existing `ecommerce-recsys` environment uses Python 3.13 and the sealed
fold-9 bundle with external manifest pin
`84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe`.
Model bytes and compatible inference implementations are checked before and
after measurement. Numerical initialization uses one thread. Cache stays off,
busy behavior remains rejection and existing security quotas are unchanged.

| Step | Fixed workload or requirement |
| :--- | :--- |
| Initial process | Exact HTTP output/route/version/cutoff/manifest parity for 100 warm references and one cold reference |
| Prefix and denial checks | Six warm/cold K-prefix requests and eight authentication, authority and request-contract denials |
| Sustained sample | 120 open-loop arrivals at 1/s: all 100 warm references once and 20 cold requests; K=20, four client workers |
| Overload sample | 32 warm arrivals at 16/s; exact successful outputs, explicit quota/busy rejection, no hidden fallback |
| Recovery | Two-second quota refill followed by warm/cold output parity and ready/idle telemetry |
| Stop and restart | Owned pipe-triggered application shutdown, zero exit, exactly one cleanup event, closed port; fresh process on the same port and all 101 reference checks repeated |
| Startup rejection | Wrong external manifest pin must produce nonzero exit with no startup-ready event or remaining listener |
| Early control EOF | Close the inherited pipe before startup; require zero exit, one cleanup, no startup-ready event and a closed port |

The sustained targets are successful warm p95 ≤300 ms, p99 ≤500 ms, no rejected
or failed arrivals and maximum dispatch lateness ≤250 ms. The intentional burst
also requires dispatch lateness ≤250 ms and both successful and rejected
requests. Recovery including quota refill must complete within ten seconds.
These targets were fixed before results were observed.

The serving child's loaded RSS target remains **2 GiB**. An external parent
samples RSS every 50 ms, with a maximum permitted gap of 200 ms including phase
boundaries. Startup and loaded phases are separate. Driver/whole-host memory is
outside serving RSS; startup peak is reported separately. The 2 GiB value is the
initial engineering target, not an enforced operating-system allocation cap.

Successful warm and cold latencies are separate. Fast 429/503 responses are
excluded from inference latency summaries. Client dispatch lateness includes
worker-queue delay. Recommendation status counts reconcile with HTTP metrics,
successful numerical calls and delivered responses; observers must be healthy
and the model idle/ready before shutdown. Sampling or identity failures prevent
receipt publication. Completed target failures remain explicit outcomes.

The receipt checker requires a fixed schema, strict integer/boolean types,
finite numbers and complete source/runtime identities. Startup sample duration
must match startup time. Workload durations and peaks must fit the containing
loaded-process scope; the full assessment must contain its measured process
phases. Contradictory summaries are rejected before acceptance is computed.
Missing/unknown fields, duplicate JSON keys and malformed or oversized receipt
files produce controlled verification errors.

## Local operation

Start the foreground service with the command in the
[local guide](LOCAL_DEMONSTRATION.md). Ctrl+C requests normal application
shutdown. Verification additionally uses `--control-stdin` with an inherited
parent-owned pipe: a stop line, invalid command or EOF requests Uvicorn's normal
shutdown. Non-pipe input is rejected. There is no HTTP administrative endpoint,
new bind address, persisted credential or automatic cloud wake-up.
Pipe stop reaches the service lifecycle while model startup may still be
running. Pre-startup EOF cannot publish readiness, and fitted-fixture tests
verify that a blocked loader drains without a later ready transition.

The verifier creates its own child processes, ephemeral bearer credentials,
private logs and selected loopback port. It checks listener ownership before
measurement, never stops a process merely because it holds a port, and confirms
port closure. Failed cleanup aborts evidence publication. A forced kill is
cleanup after a failed run and cannot count as graceful success.
Child reaping state is independent of the log handle. A closed/broken control
pipe still waits for EOF-driven shutdown or forces owned cleanup on deadline;
a failed reap remains eligible for retry even after its log has closed.

Startup, HTTP calls, total assessment and stop are bounded by 120, 10, 600 and
20 seconds respectively. This stop/restart uses the same pinned model. It is
not a different-version rollback, host power-loss recovery or a measurement of
in-flight graceful drain; prior service tests retain their separate scope.
HTTP deadlines cover connect, headers and body as one wall-clock interval.
Expiration shuts down the owned socket, including a response that sends bytes
slowly enough to evade per-read timeouts. Failed workload execution cancels
pending calls and aborts active sockets before bounded executor cleanup.

## Observed results

The [completed receipt](../benchmarks/deployment/local_release_maintenance_validation_v1.json)
records a Windows/AMD64 run on 2026-10-24, Python 3.13.15, implicit 0.7.3,
cache off and one numerical worker. The assessment took 253.744 seconds.
All seven prospective targets passed: `assessment_completed`,
`operational_passed` and `local_release_accepted` are true.
`public_deployment_eligible` remains false.

| Measurement | Result |
| :--- | ---: |
| First startup / restart to readiness | 21.449 / 17.247 s |
| Startup sampled peak RSS, first / restarted process | 1.793 / 1.797 GiB |
| Loaded sampled peak RSS, first / restarted process | 1.497 / 1.499 GiB |
| Sustained offered / completed / successful requests | 120 / 120 / 120 |
| Sustained successful warm / cold samples | 100 / 20 |
| Warm HTTP p50 / p95 / p99 | 109.186 / 209.440 / 233.063 ms |
| Cold HTTP p50 / p95 / p99 | 35.664 / 57.692 / 58.926 ms |
| Sustained dispatch maximum | 1.835 ms |
| Sustained resource samples / largest gap | 2,013 / 74.033 ms |
| Burst offered / completed | 32 / 32 |
| Burst successful / quota 429 / busy 503 | 13 / 13 / 6 |
| Burst dispatch maximum | 1.069 ms |
| Warm/cold recovery including two-second refill | 2.129 s |
| Normal shutdown, first / restarted process | 1.003 / 1.096 s |
| Pre-startup EOF shutdown | 2.608 s; zero ready events |

The first sustained arrival is scheduled at time zero and the last at 119
seconds; completion span was 119.061 seconds. This is 120 arrivals at 1/s,
not a separate 120-second post-warmup hold. Startup, parity checks and burst
are outside that timing interval. Cold latency summarizes twenty calls to the
same explicit cold context. All 100 sealed warm references appear in the
sustained sample; they are the existing narrow reference sample, not activity
strata or a representative sample of every stored user.

Both processes match all 101 sealed HTTP outputs. The first also completes six
prefix checks, eight denials, the workload and two recovery requests. Its
recommendation counters reconcile to 242 successes, four 422s, one 401, one
400, one 403, thirteen 429s and six 503s; the separate unauthenticated
readiness check accounts for the eighth denial. The restarted process has 101
successes. The burst is intentionally outside the supported steady profile;
its fast rejections are excluded from latency summaries.

Each normal stop has exit code zero, one startup-ready event, exactly one
cleanup event and confirmed port closure. A fresh instance reuses the same
port. Wrong-pin startup exits with code 3 and no startup-ready event; its owned
cleanup completes and its port is closed. A further correct-bundle child receives
EOF immediately after spawn, exits with code zero and exactly one cleanup,
publishes no startup-ready event and leaves no listener. No owned child remains after the
assessment. This is same-version process restart, not version rollback.

The current `--check` mode independently hashes the full bundle, verifies the
source/environment/policy, recomputes expected sealed-output identities and
checks receipt accounting/acceptance without loading or fitting a model.
Earlier [local HTTP evidence](../benchmarks/deployment/local_demonstration_validation_v1.json)
retains its original pre-pipe launcher fingerprint; its source identity is
historical. The current maintenance receipt binds the hardened pipe-capable
launcher, absolute-deadline client and strict classifier. Its full-package
source pin also includes the educational models. Their fit-lifecycle changes
triggered a fresh same-policy assessment; serving code, bundle bytes and target
thresholds were unchanged. The preceding
[boundary receipt](../benchmarks/deployment/local_release_boundary_validation_v1.json)
retains its original source and results. The initial local-release
[receipt](../benchmarks/deployment/local_release_validation_v1.json) retains its
original source and valid normal-path measurements; it is not a current-source
verification record. No earlier digest was edited.

## Reproduce

The full bundle and compatible environment are required. Missing real inputs
fail; no synthetic substitution or implicit test skip is used. Choose a fresh
JSON output in an existing directory:

```sh
conda activate ecommerce-recsys
python -m scripts.verify_local_release --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/local-release-repeat.json
```

The verifier uses exclusive, file-synced publication. Existing receipts are not
overwritten. Private process logs, request data, credentials and scratch helpers
remain outside Git. Directory-entry power-loss durability is not certified.

Verify the current completed evidence without rerunning the workload:

```sh
python -m scripts.verify_local_release --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --check benchmarks/deployment/local_release_maintenance_validation_v1.json
```

## Interpretation

The final Windows gate passed **1,372 unit tests** with three existing
symlink-privilege skips. The fitted-process integration profile passed **14
tests**, with the separately opt-in real-bundle case deselected. The actual
Retailrocket assessment above is independent of those synthetic fixtures.
Repository Ruff lint and formatting passed. The final full unit run used short
external scratch storage: release-controller tests reject in-checkout recovery
roots, and long Windows temp paths can exceed hard-link path limits. No frozen
release guard was weakened to accommodate the test environment.

Operational integrity, workload/resource targets and local release acceptance
are separate fields. Cloud/public deployment eligibility remains false under
this local-only contract. A short constructed workload over 101 reference
contexts does not establish maximum throughput, production traffic behavior,
activity-stratified performance, online recommendation quality or Linux
qualification of the indexed HTTP runtime. Later offline folds remain
post-selection diagnostics, not blind validation.
