# Local service load and recovery validation

## Scope and evidence

This fixed assessment exercises the unchanged historical snapshot on Docker
Desktop Linux/amd64. The [completed receipt](../benchmarks/reliability/service_resilience_boundary_validation_v1.json)
binds new and reused source, full Windows/Linux test evidence, the sealed model,
upstream capacity/qualification and release-controller identities. It follows the
[capacity assessment](HTTP_CAPACITY_REPORT.md) with longer load and explicit fault
checks. Original model, API, quotas, cache defaults and earlier receipts remain unchanged.

The [initial assessment](../benchmarks/reliability/service_resilience_validation_v1.json)
retains its original source and measurements. The current receipt records a
fresh execution of the same fixed matrix with complete-profile verification.
Each Windows JUnit identity, including parameter IDs, must match current pytest
collection. Linux evidence must match the test/configuration source and full
profile counts. Receipt identity covers executable inputs and measurements;
README and reports are maintained separately in Git.

All original-model checks use internal loopback with network none and no published
ports: non-root, read-only model/root, dropped capabilities, 2 CPUs, a 4 GiB cgroup
cap and 64 PID limit. Client and server share that cgroup. This is constructed
snapshot traffic, not a target-host deployment, production workload or statistical SLO.

## Prospective workload and fault policy

The matrix and thresholds were fixed before implementation and measurement. The
load schedule reuses 100 sealed warm contexts and one cold context: warm fraction
0.8, K=20/10/5 fractions 0.6/0.2/0.2 and deterministic reference rotation by 42.
Cache stays off; busy requests are rejected. The existing peer quota remains
5 requests/s with burst 10. No quota relaxation or inference delay is injected.
Each phase restarts its deterministic sequence; short phases visit only a subset
of the 100 warm references. This is not random population sampling.

| Scenario | Fixed scope |
| :--- | :--- |
| Sustained | 600 seconds at 1 request/s, at most 4 inflight client calls |
| Burst/recovery | Three cycles: 10 seconds at 8 requests/s (bound 16), then 20 seconds at 1 request/s (bound 4); one warm/cold recovery pair after each quiet phase |
| Memory occupancy | 180 seconds at 1 request/s (bound 4), with 512 MiB allocated and page-touched by the driver inside the same cgroup |
| Client disconnect | Observe an actual in-flight primary, close the client socket, require worker drain/readiness and all 101 post-reference outputs |
| In-flight termination | Observe a primary, send owned PID 1 SIGTERM within 50 ms, require the accepted sealed 200 response and one graceful cleanup |
| Startup dependencies | Separate wrong-pin, missing-model and corrupt-weight-overlay containers must exit nonzero within 90 seconds, never healthy or OOM-killed |
| Fresh recovery/rollback | Re-execute the frozen release controller: invalid descriptor and observer rejection, dead-target journal recovery, fresh prior-release rollback and final graceful stop |

Load uses bounded open-loop arrivals, no retries and a 10-second socket timeout.
Client shedding and dispatch lateness remain explicit. Every successful response
must match sealed Top-K, route, cutoff, version, manifest, fresh request ID and
security headers. All 101 references are checked before/after each load and
disconnect scenario at 0.26-second spacing. Termination checks all 101 before
the signal plus the accepted response. Fault scratch files never change the bundle.

## Acceptance and measurement scopes

Operational completion requires the complete fixed matrix, correct outputs,
matching telemetry and provenance, observed resource coverage and owned cleanup.
Live and resumed windows share semantic validation; a recomputed checksum cannot
repair contradictory counts, throughput, slices, sample coverage or telemetry.

Charter targets remain warm success HTTP p95 <= 300 ms, p99 <= 500 ms and serving
RSS <= 2 GiB. Steady cells also target error and rejection/client-shed fractions
<= 0.01 of all arrivals and dispatch p99 <= 10 ms. Tail classification needs at
least 100 warm successes. Short burst/quiet phase percentiles are descriptive;
their insufficient-sample flag remains visible. Fast quota/busy rejections never
enter successful inference latency. After each 20-second quiet phase, a separately
timed recovery pair must finish within 10 seconds and leave the service ready/drained.
That pair duration is not an RTO measured from the end of the burst.

PID 1 RSS/CPU are sampled nominally every 50 ms across each window and drain.
Require first sample <= 0.2 seconds, last >= duration minus 0.2 seconds, and gaps
<= 0.5 seconds. Driver CPU/RSS and cgroup peak have separate scopes. The pressure
allocation is driver occupancy, not an increase in service RSS or an OOM test.

## Measured windows

| Scenario/phase | Seconds | Offered/s | Arrivals | 200 | 503 | 429 | Shed |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| sustained/steady | 600 | 1 | 600 | 600 | 0 | 0 | 0 |
| burst-recovery/burst-1 | 10 | 8 | 80 | 55 | 4 | 21 | 0 |
| burst-recovery/quiet-1 | 20 | 1 | 20 | 20 | 0 | 0 | 0 |
| burst-recovery/burst-2 | 10 | 8 | 80 | 55 | 3 | 22 | 0 |
| burst-recovery/quiet-2 | 20 | 1 | 20 | 20 | 0 | 0 | 0 |
| burst-recovery/burst-3 | 10 | 8 | 80 | 55 | 3 | 22 | 0 |
| burst-recovery/quiet-3 | 20 | 1 | 20 | 20 | 0 | 0 | 0 |
| memory-pressure/occupied | 180 | 1 | 180 | 180 | 0 | 0 | 0 |

| Scenario/phase | Warm n | Warm p95 ms | Warm p99 ms | Serving RSS GiB | At least 100 warm successes |
| :--- | ---: | ---: | ---: | ---: | :--- |
| sustained/steady | 480 | 241.469 | 303.438 | 2.263 | Yes |
| burst-recovery/burst-1 | 44 | 225.227 | 276.645 | 2.263 | No; descriptive only |
| burst-recovery/quiet-1 | 16 | 178.491 | 290.168 | 2.263 | No; descriptive only |
| burst-recovery/burst-2 | 43 | 235.412 | 274.818 | 2.263 | No; descriptive only |
| burst-recovery/quiet-2 | 16 | 134.411 | 215.101 | 2.263 | No; descriptive only |
| burst-recovery/burst-3 | 43 | 215.144 | 232.511 | 2.263 | No; descriptive only |
| burst-recovery/quiet-3 | 16 | 109.902 | 206.249 | 2.263 | No; descriptive only |
| memory-pressure/occupied | 144 | 228.778 | 256.336 | 2.263 | Yes |

These eight windows contain 1,080 offered arrivals. Results belong to this
single fixed run; no cell was retuned using observed outcomes. See the receipt
for separate cold/rejection latency, dispatch, sample coverage, CPU and cgroup peaks.

The memory scenario observed 512.004 MiB additional driver RSS for the declared
512 MiB allocation; its cgroup peak was 2.749 GiB. These values are separate from
the serving RSS column and do not establish an OOM envelope.

- **sustained**: failed declared targets: rss; rejection fraction 0.000000 of arrivals.
- **memory-pressure**: failed declared targets: rss; rejection fraction 0.000000 of arrivals.

Assessment completion is distinct from meeting those targets. Deployment
eligibility remains false; a 4 GiB cgroup cap does not revise the 2 GiB RSS budget.

## Lifecycle, startup and recovery evidence

- Client disconnect: the observed numerical worker drained in 0.060438 seconds; readiness and all 101 post-reference outputs passed.
- In-flight SIGTERM: observation-to-signal 0.084 ms; the accepted request returned the sealed 200 response, followed by exactly one graceful cleanup.
- startup-bad-pin: exit code 3 after 2.811 seconds; never healthy, no OOM, owned removal confirmed.
- startup-missing: exit code 3 after 2.752 seconds; never healthy, no OOM, owned removal confirmed.
- startup-corrupt: exit code 3 after 7.605 seconds; never healthy, no OOM, owned removal confirmed.
- Fresh release exercise: three normal candidates each passed 101 references, with the unchanged model/image; descriptor/observer rejection, dead-target recovery, fresh rollback and final stop passed.

The direct lifecycle/load scenarios include 909 paced reference checks, six
post-burst recovery references and the one accepted termination response. The
fresh release exercise adds 303 reference outputs plus its own prefix/denial
checks. These are regression parity checks, not new recommendation accuracy.

A wire disconnect does not prove ASGI-task cancellation. Event-controlled fixture
tests separately cancel a waiter while numerical work is blocked, assert a second
call remains busy, and prove stop waits for the worker. Fixture model and executor
failures invalidate readiness without hidden cold success; a fresh service can
start after cleanup. No fault hook is added to the real service or image.

Full gates passed 1,072 Windows unit and 11 fitted-process cases (one allowed
symlink-privilege skip), and 1,073 Linux unit plus 11 fitted-process cases (no
skips). The 61 new unit and two fitted cases are included. Linux regression ran
locally in the pinned CPU CI image; it is not a new remote GitHub qualification.

## Reproduction and ownership

Use ecommerce-recsys Python 3.13 with the declared release-test dependencies,
the complete sealed original bundle and qualified image. Run full Windows
unit/fitted profiles with explicit JUnit, then the pinned Linux CI reproduction.
The verifier collects the complete current Windows unit and fitted profiles and
compares their exact JUnit identities, including parameter IDs. Missing,
substituted or duplicate cases and unexpected skips fail. Linux evidence binds every
test/configuration input and requires complete profile counts. Missing inputs
fail before any original-model measurement.

The Linux gate uses the [release test locks and tooling](RELEASE_WORKFLOW.md).
The example assumes their pinned wheelhouse and actionlint archive are available
under `C:/recsys-inputs/`.

```powershell
python -m pytest tests/unit -q --junitxml .local/unit.xml
python -m pytest tests/integration -m "not real_bundle" -q --junitxml .local/fixture.xml
python scripts/verify_ci_profile.py --wheelhouse C:/recsys-inputs/ci-wheels --actionlint-archive C:/recsys-inputs/actionlint_linux_amd64.tar.gz --output .local/linux-ci.json
python scripts/verify_service_resilience.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --work-root C:/recsys-operations/resilience-repeat --unit-junit .local/unit.xml --fixture-junit .local/fixture.xml --linux-ci .local/linux-ci.json --output .local/resilience-repeat.json
```

Use a fresh output and an absolute work root physically outside checkout. The
root contains source/policy/model/machine/test-bound checkpoints and exact owned
container journals. A completed cell advances only after validated evidence and
confirmed removal. Resume matching completed cells; unfinished ownership or a
completed child receipt without its parent checkpoint requires explicit operator
inspection. The child release controller retains its own journal/recovery rules.
Do not discard state or move controller source while instances remain owned.

## Limits and remaining release gates

Ten minutes of constructed sustained traffic does not establish a production
soak result, population-wide capacity, statistical tail confidence or a load SLO.
Memory occupancy is bounded at 512 MiB; actual OOM, CPU exhaustion, network
partitions and external database/cache outages were not exercised. Startup-file
rejection and fixture dependency faults have the distinct scopes stated above.

A/B recovery uses the same model and isolated controller. It does not establish
public traffic switching, zero downtime, daemon/host power-loss recovery or native
target-host behavior. Dual-instance transitions require RAM headroom. Resource
budgets and target-host deployment gates remain separate; no budget is waived.

Previously inspected offline folds 5–9 remain post-selection diagnostics, not
blind validation. No model retuning, new quality score or online business impact
is established by this operational evidence.
