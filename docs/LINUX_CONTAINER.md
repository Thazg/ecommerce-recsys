# Isolated Linux snapshot container

## Scope

The container packages the existing snapshot HTTP service for **Linux/amd64**.
It installs the unchanged Python package and loads the original fold-9 bundle
from a read-only mount. It does not fit models, change ranking, copy training
data into the image or expose an endpoint outside the container.

Qualification uses Docker Desktop's Linux backend on this Windows host. The
container has no external network or published ports; operator probes execute
against its internal loopback interface. This verifies a specific Linux runtime
and finite reference sample. Native deployment-host recovery, representative
load, image publication and controlled releases require separate evidence.

## Build and artifact delivery

The [Dockerfile](../containers/Dockerfile) uses two stages with the same
immutable Python 3.13.15 Debian Bookworm base:

```text
python:3.13.15-slim-bookworm@sha256:3e2de9c40ca4e3d73240059f9d48baff27908f10293e985a2f382a0378e6df4a
```

The [build lock](../containers/build.lock) pins the wheel builder. The
[runtime lock](../containers/runtime.lock) pins every direct and transitive
Python dependency with a wheel SHA-256. Numerical versions match the original
bundle. The Debian OpenMP library is independently pinned by package checksum.
The final stage contains no compiler, Git, project scripts, datasets or model
bundle. The [.dockerignore](../.dockerignore) allows only package source,
unchanged project metadata and the selected container files into the context.
Directory-wide re-inclusion and Dockerfile-specific ignore overrides are
rejected. Before the model build, the verifier uses Docker's local exporter
to inspect the actual context of nonsecret fixtures: nine allowed files must
survive and twelve private/env/cache/data/model/test/script canaries must not.
Nested Python sources are included. This exercises Docker matching semantics
rather than relying on a textual comparison of ignore patterns alone.

```sh
docker build --platform linux/amd64 -f containers/Dockerfile -t recsys-snapshot:qualification .
```

Pinning the base digest follows Docker's
[build guidance](https://docs.docker.com/build/building/best-practices/).
The verification receipt records the actual local image content ID. Pinned
inputs do not establish byte-identical wheel/image rebuilding, a registry
release digest or automatic security updates. Dependency updates require a new
qualification; the historical bundle's numerical compatibility remains a gate.

The model stays under ignored `artifacts/retailrocket-fold09-v1/`. Its external
manifest pin is:

```text
84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe
```

The loader checks the complete inventory before readiness. Missing components,
corrupt bytes and the wrong external manifest pin must fail startup. No
fixture, fresh training run or cold success substitutes for an invalid bundle.

## Execution policy

| Setting | Qualification value |
| :--- | :--- |
| Platform | Linux/amd64 |
| User and group | `10001:10001` |
| Inference | Original launcher, one active numerical worker, numerical threads set to one |
| Network | `none`; internal `127.0.0.1:8000`, no published ports |
| Storage | Read-only root and `/model`; bounded `/tmp` tmpfs |
| Privileges | All capabilities dropped, `no-new-privileges`, no privileged mode |
| CPU / process bounds | 2 CPUs, 64 PIDs |
| Memory / total memory-plus-swap | 4 GiB / 4 GiB |
| Temporary storage | 16 MiB, `noexec,nosuid,nodev` |
| Readiness | Internal bounded HTTP check, 10-second interval, 90-second startup period |
| Shutdown | SIGTERM with a 30-second stop grace period; owned cleanup must complete |
| Service mode | Cache disabled, busy requests rejected, default local anonymous access |

These are explicit
[container execution controls](https://docs.docker.com/engine/containers/run/),
not a whole-service security certification. The 4 GiB cap accommodates the
existing snapshot; it does **not** revise the charter's **2 GiB serving RSS**
target. The supported HTTP launcher remains loopback-only. Publishing a host
port alone does not make it reachable or authorize changing its bind policy.
Public exposure, authentication design and representative concurrent traffic
are outside this qualification.

For an operator session on this Windows host, resolve the model directory and
the built image's content ID before creating the container:

```powershell
$snapshotBundle = (Resolve-Path artifacts/retailrocket-fold09-v1).Path
$snapshotImage = docker image inspect recsys-snapshot:qualification --format '{{.Id}}'
docker run -d --name recsys-snapshot --platform linux/amd64 `
  --network none --user 10001:10001 --read-only `
  --cap-drop ALL --security-opt no-new-privileges `
  --pids-limit 64 --cpus 2 --memory 4g --memory-swap 4g `
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777 `
  --stop-timeout 30 `
  --mount "type=bind,source=$snapshotBundle,target=/model,readonly" `
  --env RECSYS_MANIFEST_SHA256=84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe `
  $snapshotImage
docker inspect recsys-snapshot --format '{{.State.Health.Status}}'
# Wait for healthy before running the finite HTTP probe.
docker exec recsys-snapshot python /opt/runtime/probe.py http
docker stop --time 30 recsys-snapshot
docker rm recsys-snapshot
```

Choose an unused container name and retain its identity for cleanup. The
automated verifier below additionally checks installed code/dependencies,
producer/Linux array parity and startup faults, and owns cleanup on failure.
The HTTP probe requires a fresh process; create a new container for a repeat.

## Cross-platform numerical policy

The original Windows bundle and the
[functional integration gate](TESTING_AND_RELEASE_GATES.md) retain exact
feature/score digest comparisons. Their files and receipts are unchanged.

An initial Linux probe failed that bitwise gate: all 100 warm feature and score
digests differed, while all 101 candidate pools, evidence digests, routes and
ordered Top-20 lists matched. A separately approved cross-platform policy was
then fixed before the complete numerical/HTTP qualification. It is a disclosed
acceptance-policy revision after an observed failure, not a blind numerical test.

The [qualification helper](../containers/qualification.py) exports private
feature/score arrays in the original Windows producer environment **only after
each trace exactly matches its sealed producer reference**. Export observes the
original digest inputs and returns the original hashes unchanged. An external
metadata pin binds the archive checksum, original manifest, reference order,
reader code and numerical environment. The archive is mounted read-only for
the isolated model probe and is absent from the service container and Git.

For every one of the 101 references, Linux must preserve:

- Candidate pool order, evidence digest, route and ordered output **exactly**.
- Feature/score shape and `float64` dtype exactly, with all values finite.
- Every feature and score within `rtol = atol = 1e-12`, with the Windows array
  as reference: `abs(linux - windows) <= 1e-12 + 1e-12 * abs(windows)`.

The numeric rule follows
[NumPy's allclose definition](https://numpy.org/doc/stable/reference/generated/numpy.allclose.html).
Broadcasting and NaN equality are forbidden. No rounding, model-math patch,
reference replacement or manually changed SHA is used. The receipt separately
reports `bitwise_parity`; passing this Linux policy does not turn that field
true or certify unmeasured users.

## Verify the real snapshot

Activate `ecommerce-recsys` on the original Windows producer host, ensure the
complete pinned bundle is present and start Docker's Linux engine. From the
repository root:

```sh
python scripts/verify_linux_container.py --bundle artifacts/retailrocket-fold09-v1 --manifest-sha256 84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe --output benchmarks/containers/linux_snapshot_boundary_validation_v1.json
```

The verifier builds the image, validates installed source/dependency identity
and resource controls, exports producer-exact numerical references, checks all
101 Linux traces and exercises real HTTP. HTTP checks include 100 warm/one
cold output comparisons, six prefix calls, an unknown-user cold route, four
input/access denials and a successful recovery. Calls are paced below the
service's default attempt quota. A successful stop must emit exactly one owned
cleanup event. Every cleanup attempts owned removal and then requires a
successful daemon query confirming that exact container name is absent. A
remaining container or failed confirmation aborts success publication. An
already-absent container is accepted only after independent confirmation.
The private `.local/` scratch parent is created when missing, including on a
fresh checkout. Reported model/serving RSS and cgroup peak must be bounded
positive integer byte counts; bools, floats, missing or invalid values fail.

The verifier publishes complete evidence atomically and refuses to overwrite an
existing path. Use a fresh output path for repeats. Private arrays, wheels,
build logs and scratch state remain under ignored `.local/`. This combined
producer-and-Linux verification command requires the original producer runtime
for its exact reference export; it is not a Linux-only reproduction command.

## Results and remaining gates

The [current Linux receipt](../benchmarks/containers/linux_snapshot_boundary_validation_v1.json)
records successful qualification on Docker Engine 29.6.2, Docker Desktop's
Linux/amd64 backend and kernel `6.18.33.2-microsoft-standard-WSL2`.
The [earlier receipt](../benchmarks/containers/linux_snapshot_validation_v1.json)
retains the original source and measurements. Its outputs remain historical
evidence; it predates context-export, scratch-parent, cleanup-confirmation and
memory-telemetry hardening and is not expected to match current runner hashes.

| Check | Result |
| :--- | :--- |
| Original Windows traces before numerical export | 101/101 exact |
| Linux pool, evidence, route and ordered Top-20 | 101/101 exact |
| Linux feature/score arrays under the declared bound | 101/101 references pass |
| Maximum absolute feature / score error | `8.881784197001252e-16` / `1.1102230246251565e-15` |
| Bitwise feature/score parity | False; all 100 warm digests differ, cold matches |
| HTTP reference / prefix / unknown-cold checks | 101 / 6 / 1 pass |
| HTTP denial / recovery checks | 4 / 1 pass |
| Invalid startup | Wrong pin, missing model and corrupt component rejected |
| Docker context export | Nine allowed files included; twelve private canaries excluded |
| SIGTERM stop | One owned cleanup event; no owned containers left |

The same receipt contains the following **100-warm-reference**, cache-off,
sequential internal-loopback HTTP measurements, with 0.26-second minimum spacing
between request starts and a new TCP connection per call:

| Measurement | Value |
| :--- | ---: |
| Startup to Docker healthy | 33.18 s |
| Warm client p50 / p95 / p99 | 67.30 / 230.69 / 308.47 ms |
| Serving-process RSS before / after requests | 2.26 / 2.26 GiB |
| Cgroup memory peak | 2.38 GiB |

Serving RSS exceeds the **2 GiB** target; `deployment_eligible` remains false.
Sequential client timings, serving-process RSS samples and cgroup peak have
different scopes. The cgroup peak includes qualification subprocesses and file
cache; it is not peak serving-process RSS. Startup-to-healthy includes health
polling. None of these measurements establishes a production latency objective.
They also do not establish a Windows-to-Linux performance improvement: host,
CPU allocation and probe scopes differ. Earlier receipts remain unchanged.

Linux qualification does not recompute recommendation accuracy or change the
locked model policy. Historical full-fold quality remains in the
[bundle report](MODEL_ARTIFACTS.md); folds 5–9 remain post-selection diagnostics.
Controlled release/rollback, target-host failure recovery, representative load,
memory optimization and public deployment remain separate gates.

## Regression checks

Use the `ecommerce-recsys` environment with the declared development and serving
test dependencies:

```sh
python -m pytest tests/unit tests/integration -m "not real_bundle" -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
```

The Windows regression run passed **832 tests**, including 84 container-policy
cases, with one symlink test skipped because the host lacks that Windows
privilege. One real-bundle test is deselected by this command; it is not counted
as executed. The separate real Linux qualification above includes original
Windows trace export and Linux model/HTTP execution. Test coverage includes
numeric bounds, shape/dtype/NaN rejection, exact-field changes, reference
lineage, unsafe image/container configurations, build-context admission,
bounded authenticated readiness and cleanup after failed creation.
