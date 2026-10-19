# Snapshot integration and functional release gates

## Scope

The functional gate verifies the installed snapshot package, the actual HTTP
launcher and their test coverage against one immutable model bundle. It keeps
synthetic-model tests separate from Retailrocket reference checks. It does not
train a new Retailrocket model, repeat full-fold accuracy or authorize deployment.

The [validation receipt](../benchmarks/release/integration_boundary_validation_v1.json)
records the test/source identities, numerical environment, external model and
quality pins, executed profiles and fresh loader/HTTP evidence. Earlier
[model](MODEL_ARTIFACTS.md), [API](RECOMMENDATION_API.md),
[cache](SERVICE_CACHE_AND_FALLBACKS.md), [observability](OBSERVABILITY.md) and
[input-boundary](API_HARDENING.md) receipts retain their original bytes and scope.

## Evidence layers

| Layer | Execution | What it establishes | Boundary |
| :--- | :--- | :--- | :--- |
| Unit regressions | `tests/unit/` | Causality, deterministic ordering, request/schema validation, cache/failure/admission ownership, socket guards and evidence rejection | Fixtures and controlled faults do not establish real-model accuracy or workload behavior |
| Fitted process integration | `tests/integration/test_snapshot_http.py` | Actual synthetic ALS/ItemKNN/popularity state is exported, loaded and served by a child launcher over loopback HTTP | Small generated data; no Retailrocket quality or memory claim |
| Explicit real-bundle profile | `tests/integration/test_snapshot_references.py` | Isolated package loader reproduces all 100 warm and one cold sealed producer traces | One historical snapshot and a finite reference set; no refit or full-fold quality recomputation |
| Real HTTP verification | Unchanged `verify_service_hardening.py`, invoked by the functional gate | Fresh off/miss/hit output parity, access/input denials, recovery, telemetry reconciliation and sampled resources | Paced Windows loopback sample with new TCP connections; no representative load or SLA |
| Historical full-fold quality | Externally pinned `benchmarks/artifacts/fold09_v1.json` | Prior complete loaded-policy reconciliation belongs to this exact manifest and component inventory | Historical evidence, independently identified; not recomputed by this gate |

Synthetic integration uses real fitted sources and the real producer, exporter,
package loader and server. It does not replace HTTP or model execution with mocks.
The tests exercise anonymous/cache-off and bearer/cache-on modes, known/unknown
and exhausted histories, `k=1/5/10/20`, prefix reuse, fresh request IDs, catalog and
full seen-set filtering, rejection followed by healthy inference, bad manifest
pins, corrupt/missing components and listener stop/restart.

Controlled unit tests retain responsibility for deliberately blocked workers,
busy fallback, cache faults, cancellation and owned startup/shutdown drain.
Windows background-process integration verifies forced stop/restart; it does
not demonstrate graceful console signaling. The POSIX test path requests
SIGTERM and checks the cleanup event. A configured Ubuntu CI job is separate
from evidence that a particular CI run or the full Retailrocket bundle passed.

## Numerical and output policy

The real loader must reproduce candidate order and the producer's digests for
source evidence, transformed features and scores, plus ordered Top-K IDs and
route. Comparison is exact, without an epsilon. These checks reuse the
unchanged package-only reader and producer references; they do not permit a fit
call or a manually substituted hash. The numerical versions and inference code
must satisfy the [bundle contract](MODEL_ARTIFACTS.md).

HTTP checks compare ordered item IDs, route, version, cutoff and manifest for
all references in both modes, with explicit prefix and canonical-cold checks.
Server-generated request IDs must be valid and fresh rather than equal to a
historical ID. Headers, access controls, worker/delivery counters, transport
events and owned logs are verified separately from recommendation equality.

Exact parity on a finite reference set is a regression check, not proof of
equivalence for every possible request. It does not turn the previously
inspected folds 5–9 into blind validation or change the offline selection rule.

The later [Linux container qualification](LINUX_CONTAINER.md) has a separate
cross-platform numerical policy. It preserves exact pool/evidence/output order
and bounds feature/score differences; it does not relax this same-host gate or
change its original receipt. Reproduce the published functional receipt from
revision `d8e4a31`; subsequent container scripts/tests and checkout rules change
the broad source fingerprint, while the measured model/HTTP implementation
remains unchanged. A new current-tree functional run needs a fresh receipt path.

## Run the profiles

Use Python 3.13 and install the declared service test dependencies:

```sh
python -m pip install -e ".[dev]" -r requirements/serving-test.txt
python -m pip check
python -m pytest tests/unit -q -o xfail_strict=true
python -m pytest tests/integration -m "not real_bundle" -q -o xfail_strict=true
```

The real-bundle profile requires the external fitted bundle and a trusted
manifest pin. It fails on missing opt-in configuration, wrong pins or a
selection that contains no real-bundle test:

```sh
python -m pytest tests/integration -m real_bundle --run-real-bundle --bundle-path artifacts/retailrocket-fold09-v1 --bundle-manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
```

The quality receipt defaults to the published fold-9 file with its independent
SHA-256 pin. To verify another supported snapshot, supply both
`--bundle-quality-receipt` and `--bundle-quality-sha256`. A normal `pytest` run
explicitly skips the real-bundle case; that run alone cannot satisfy the
functional gate. CI runs the unit and fitted-process profiles without downloading
Retailrocket data or a fitted production-size bundle.

Run the complete functional gate from the repository root, using a fresh output:

```sh
python scripts/verify_release.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output .local/integration_repeat.json
```

The gate runs dependency imports, dependency integrity, Ruff, unit regressions,
fitted-process integration, real loader references and real HTTP verification
sequentially. It strips inherited pytest filters/plugins and operator credentials
from child environments. Private logs, JUnit, temporary fixtures and intermediate
evidence remain in a unique ignored `.local/release-verification-*` directory.
No raw inputs, credentials, absolute workspace paths or raw event logs are added
to the public receipt.

## Failure and publication rules

- A failed command, incomplete profile, failed/duplicate JUnit case, unexpected
  skip, stale source identity or inconsistent evidence aborts the gate. Each
  profile must execute successful cases; fixture evidence cannot replace real
  bundle evidence. Case modules must belong to the executed profile; the real
  profile requires its designated producer-reference case. Only UTF-8 JUnit
  without DTD/entities or unexecuted case status is accepted. Strict xfail
  handling rejects unexpected passes.
- The Windows symlink-privilege skip and missing optional Torch/Faiss experiment
  dependencies are the only named unit-profile exceptions. Service and
  integration dependency skips cannot satisfy the gate. Successful-case floors
  protect against accidentally running a reduced suite; they are not a coverage
  percentage or proof that every future regression has a test.
- The manifest, component inventory, trusted quality file, measured sources and
  numerical environment are checked around execution. Evidence digests, loader
  reference counts, HTTP policy/outputs, counter reconciliation and cache smoke
  gates are validated before publication. HTTP latency paths require exactly
  100 warm and one cold sample per applicable off/miss/hit path, finite positive
  summaries, ordered percentiles and consistent single-sample values. Startup
  duration must be finite and positive; RSS sampling must retain the declared
  50 ms interval. Empty zero-valued summaries cannot satisfy the ratio gates.
- Owned commands have deadlines and tracked descendants are terminated on
  timeout/failure. This is cleanup for the controlled test workload, not OS-level
  sandboxing or a general guarantee against arbitrary detached descendants.
- Only a completed successful record is published. A same-filesystem hard link
  exposes complete fsynced JSON without replacing an existing destination.
  Unsupported publication fails; there is no overwrite fallback. Directory-entry
  power-loss durability is not certified, and a killed process may leave private
  staging files. Reverification requires a fresh output path.

## Recorded verification

The [v1 receipt](../benchmarks/release/integration_boundary_validation_v1.json) completed
on 2026-10-18 with Windows/AMD64, Python 3.13.15 and the unchanged fold-9 bundle.
It binds 154 package/script/test/configuration files and the external manifest
and quality pins. The sequential gate took approximately 276 seconds on this
host; this includes tests and probes, rather than model fitting or a serving
latency measurement.

| Profile | Passed cases | Skipped cases | Reference scope |
| :--- | ---: | ---: | :--- |
| Unit | 741 | 1 | Named Windows symlink-privilege exception |
| Fitted HTTP process | 7 | 0 | Synthetic fitted state, real launcher and network |
| Explicit real bundle | 1 | 0 | All 100 warm and one cold sealed traces |

The profiles total **749 passed cases and one allowed skip**. Dependency imports,
`pip check`, Ruff lint and formatting also passed. This total comes from the
three explicit profiles; a default run omits real-bundle execution.

Fresh HTTP evidence reconciles 136/238 invocations, 111/211 deliveries and
111/101 primary calls for anonymous-off/bearer-on, respectively, with zero
observer errors. All 100 warm and one cold outputs match the sealed references
through off/miss/hit paths. Prefix, canonical-cold and denial-recovery checks
pass, together with the original prospective cache ratio smoke gates.

| Warm client path | p95 ms |
| :--- | ---: |
| Anonymous, cache off | 233.57 |
| Bearer, first miss | 249.39 |
| Bearer, cache hit | 30.21 |

These are 100-reference, paced loopback samples with a new TCP connection per
call. Credential and cache settings differ between processes, so the experiment
does not isolate their individual overhead. The single cold reference does not
define a latency distribution. Anonymous-off/bearer-on processes have **2.19/2.23 GiB
ready RSS and 2.41/2.44 GiB sampled peak RSS**, exceeding the 2 GiB charter budget;
50 ms sampling lower-bounds the true peak. No load or deployment budget is
certified by these timings.

## Deployment boundary

`functional_passed` and `deployment_eligible` are separate fields. Functional
success requires the checks above; the receipt deliberately records
`deployment_eligible: false`. This gate alone does not verify Linux execution;
later [container evidence](LINUX_CONTAINER.md) qualifies a finite Linux sample.
Representative load and target-host recovery remain unverified. The sampled 2 GiB memory budget
is evaluated explicitly and is not waived by output parity or a cache speedup.

The [roadmap](ROADMAP.md) separately defines container reproduction, controlled
release/rollback and workload qualification. No image,
registry publication, release tag, hot replacement or public service is created
by this command.
