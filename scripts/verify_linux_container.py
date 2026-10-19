"""Build and qualify an isolated nonroot Linux snapshot; never publish an image."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, file_sha, verify_inventory

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from containers.qualification import POLICY, build_reference  # noqa: E402
from scripts.release_validation import QUALITY_PATH, QUALITY_PIN, validate_quality  # noqa: E402
from scripts.verify_release import publish  # noqa: E402

IMAGE = "recsys-snapshot:qualification"
BASE = "python:3.13.15-slim-bookworm@sha256:3e2de9c40ca4e3d73240059f9d48baff27908f10293e985a2f382a0378e6df4a"
MEMORY = 4 * 1024**3


def sources():
    paths = [
        ROOT / ".dockerignore",
        ROOT / ".gitattributes",
        ROOT / "pyproject.toml",
        ROOT / "scripts/verify_linux_container.py",
        ROOT / "tests/unit/test_linux_container.py",
        *[
            ROOT / "containers" / name
            for name in (
                "Dockerfile",
                "runtime.lock",
                "build.lock",
                "probe.py",
                "healthcheck.py",
                "qualification.py",
            )
        ],
        ROOT / "scripts/release_validation.py",
        ROOT / "scripts/verify_release.py",
        *sorted((ROOT / "src/ecommerce_recsys").rglob("*.py")),
    ]
    return {p.relative_to(ROOT).as_posix(): file_sha(p) for p in paths}


def validate_context():
    expected = {
        "**",
        "!pyproject.toml",
        "!src/ecommerce_recsys/**/*.py",
        *[
            "!containers/" + name
            for name in (
                "Dockerfile",
                "runtime.lock",
                "build.lock",
                "probe.py",
                "healthcheck.py",
                "qualification.py",
            )
        ],
    }
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    if not lines or lines[0] != "**" or set(lines) != expected or len(lines) != len(expected):
        raise ValueError("Build context must use the explicit source-only allowlist.")
    override = ROOT / "containers/Dockerfile.dockerignore"
    if override.exists() or override.is_symlink():
        raise ValueError("Dockerfile-specific context overrides are not supported.")


def scratch_directory():
    parent = ROOT / ".local"
    parent.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="linux-qualification-", dir=parent))


def verify_context(scratch):
    """Ask Docker to export its actual filtered context, using nonsecret canaries."""
    context = scratch / "context-canaries"
    context.mkdir()
    (context / ".dockerignore").write_bytes((ROOT / ".dockerignore").read_bytes())
    allowed = [
        "pyproject.toml",
        "src/ecommerce_recsys/allowed.py",
        "src/ecommerce_recsys/nested/allowed.py",
        *[
            "containers/" + name
            for name in (
                "Dockerfile",
                "runtime.lock",
                "build.lock",
                "probe.py",
                "healthcheck.py",
                "qualification.py",
            )
        ],
    ]
    excluded = [
        ".env",
        ".git/config",
        ".local/private.txt",
        "data/raw/canary.csv",
        "artifacts/model.npy",
        "tests/private.py",
        "scripts/private.py",
        "containers/private.env",
        "containers/__pycache__/private.pyc",
        "src/ecommerce_recsys/private.env",
        "src/ecommerce_recsys/nested/private.env",
        "src/ecommerce_recsys/__pycache__/private.pyc",
    ]
    for name in [*allowed, *excluded]:
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"nonsecret build-context canary\n")
    recipe = scratch / "ContextProbe.Dockerfile"
    recipe.write_bytes(b"FROM scratch\nCOPY . /\n")
    output = scratch / "context-export"
    docker(
        [
            "build",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--file",
            str(recipe),
            "--output",
            f"type=local,dest={output}",
            str(context),
        ],
        scratch,
        timeout=90,
    )
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != set(allowed) or any(
        (output / name).read_bytes() != b"nonsecret build-context canary\n" for name in allowed
    ):
        raise ValueError("Docker admitted private canaries or excluded required source files.")
    return {
        "canary_verified": True,
        "allowed_files": sorted(allowed),
        "excluded_canaries": sorted(excluded),
    }


def locked_packages(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z0-9-]+)==([a-zA-Z0-9.]+) --hash=sha256:([a-f0-9]{64})", line)
        if not match or match[1] in result:
            raise ValueError("Runtime lock must contain unique exact hashed wheels.")
        result[match[1]] = match[2]
    if not result:
        raise ValueError("Runtime lock is empty.")
    return result


def docker(arguments, scratch, *, timeout=180, check=True):
    result = subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    with (scratch / "docker.log").open("a", encoding="utf-8") as log:
        log.write(result.stdout + result.stderr)
    if check and result.returncode:
        raise ValueError("Container command failed; inspect private Docker log.")
    return result


def inspect(kind, value, scratch):
    result = json.loads(docker([kind, "inspect", value], scratch).stdout)
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Expected one inspected Docker object.")
    return result[0]


def validate_image(image):
    config = image["Config"]
    if (
        image["Os"] != "linux"
        or image["Architecture"] != "amd64"
        or config["User"] != "10001:10001"
        or config["Entrypoint"] != ["python", "-m", "ecommerce_recsys.serving"]
        or config["Cmd"] != ["--bundle-path", "/model", "--port", "8000"]
        or config.get("ExposedPorts")
        or config.get("Volumes")
        or config["Healthcheck"]["Test"] != ["CMD", "python", "/opt/runtime/healthcheck.py"]
        or any(
            config["Healthcheck"].get(k) != v
            for k, v in {
                "Interval": 10_000_000_000,
                "Timeout": 5_000_000_000,
                "StartPeriod": 90_000_000_000,
                "Retries": 3,
            }.items()
        )
        or any(
            f"{k}=1" not in config["Env"]
            for k in (
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "PYTHONDONTWRITEBYTECODE",
            )
        )
        or config.get("StopSignal") != "SIGTERM"
    ):
        raise ValueError("Image architecture, nonroot entrypoint or health contract differs.")
    return image["Id"]


def validate_container(state, image_id, *, reference=False):
    host, config = state["HostConfig"], state["Config"]
    expected_mounts = {"/model", *(["/reference"] if reference else [])}
    mounts = state["Mounts"]
    if (
        state["Image"] != image_id
        or config["User"] != "10001:10001"
        or host["NetworkMode"] != "none"
        or host.get("PortBindings")
        or host.get("PublishAllPorts")
        or host["Privileged"]
        or host.get("CapAdd")
        or host.get("CapDrop") != ["ALL"]
        or host.get("SecurityOpt") not in (["no-new-privileges"], ["no-new-privileges:true"])
        or host["ReadonlyRootfs"] is not True
        or host["PidsLimit"] != 64
        or host["Memory"] != MEMORY
        or host["MemorySwap"] != MEMORY
        or host["NanoCpus"] != 2_000_000_000
        or set(host.get("Tmpfs", {})) != {"/tmp"}
        or host["Tmpfs"]["/tmp"] != "rw,noexec,nosuid,nodev,size=16777216,mode=1777"
        or len(mounts) != len(expected_mounts)
        or {m["Destination"] for m in mounts} != expected_mounts
        or any(m["RW"] is not False or m["Type"] != "bind" for m in mounts)
    ):
        raise ValueError("Container network, privilege, mount or resource policy differs.")
    return {
        "uid": 10001,
        "gid": 10001,
        "network": "none",
        "published_ports": False,
        "read_only_root": True,
        "read_only_model": True,
        "capabilities": "all dropped",
        "no_new_privileges": True,
        "pids_limit": 64,
        "cpus": 2,
        "memory_limit_bytes": MEMORY,
        "memory_swap_limit_bytes": MEMORY,
        "tmpfs_bytes": 16777216,
    }


def validate_runtime(data, manifest):
    expected = locked_packages(ROOT / "containers/runtime.lock")
    expected.update({"pip": "26.2.1", "ecommerce-recsys": "0.0.0"})
    package = ROOT / "src/ecommerce_recsys"
    hashes = {p.relative_to(package).as_posix(): file_sha(p) for p in sorted(package.rglob("*.py"))}
    probe_hashes = {p.name: file_sha(p) for p in (ROOT / "containers").glob("*.py")}
    numeric = data["numeric"]
    if (
        data["uid"] != 10001
        or data["gid"] != 10001
        or data["system"] != "Linux"
        or data["machine"] != "x86_64"
        or data["packages"] != expected
        or data["scripts_available"] is not False
        or data["training_directories_present"] is not False
        or data["compiler_or_git_present"] is not False
        or data["package_sources_sha256"] != hashes
        or data["probe_sources_sha256"] != probe_hashes
        or data["runtime_lock_sha256"] != file_sha(ROOT / "containers/runtime.lock")
        or numeric["python"].split(".")[:2] != ["3", "13"]
        or any(
            numeric[k] != v
            for k, v in manifest["runtime"].items()
            if k not in {"python", "system", "machine"}
        )
    ):
        raise ValueError("Installed Linux runtime differs from pinned source/dependencies.")


def validate_evidence(model, http, pin, reference_pin):
    if (
        model["manifest_sha256"] != pin
        or model["references_sha256"] != reference_pin
        or model["policy"] != POLICY
        or model["references"] != 101
        or model["warm_references"] != 100
        or model["cold_references"] != 1
        or model["qualification_passed"] is not True
        or model["mismatches"]
    ):
        raise ValueError("Model reference qualification is incomplete or failed.")
    for row in model["array_errors"].values():
        if (
            set(row) != {"max_abs_error", "max_error_over_allowed"}
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in row.values()
            )
            or row["max_error_over_allowed"] > 1
        ):
            raise ValueError("Model numerical error exceeds the approved bound.")
    if set(model["array_errors"]) != {"features", "scores"}:
        raise ValueError("Both complete numerical comparisons are required.")
    if (
        type(model.get("bitwise_parity")) is not bool
        or not isinstance(model.get("bitwise_mismatches"), list)
        or model["bitwise_parity"] != (not model["bitwise_mismatches"])
    ):
        raise ValueError("Bitwise disclosure differs from comparison outcomes.")
    expected = {
        "warm_references": 100,
        "cold_references": 1,
        "prefix_checks": 6,
        "unknown_cold_checks": 1,
        "denial_checks": 4,
        "recovery_checks": 1,
        "primary_calls": 109,
        "request_ids": 115,
        "exact_outputs": True,
        "pacing_seconds": 0.26,
        "cache_enabled": False,
        "busy_policy": "reject",
        "all_passed": True,
    }
    if any(type(http.get(k)) is not type(v) or http[k] != v for k, v in expected.items()):
        raise ValueError("HTTP qualification is incomplete or has unexpected scope.")
    memory = [
        model.get("rss_after_references_bytes"),
        *[
            http.get(k)
            for k in (
                "serving_rss_before_requests_bytes",
                "serving_rss_after_requests_bytes",
                "cgroup_memory_peak_bytes",
            )
        ],
    ]
    if any(type(value) is not int or not 0 < value <= 2**63 - 1 for value in memory):
        raise ValueError("Memory measurements must be bounded positive integer byte counts.")
    timing = http["warm_client_timing"]
    if (
        set(timing)
        != {
            "latency_samples",
            "latency_avg_ms",
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
        }
        or type(timing["latency_samples"]) is not int
        or timing["latency_samples"] != 100
        or any(
            type(v) not in (float, int) or not math.isfinite(v) or v <= 0
            for k, v in timing.items()
            if k != "latency_samples"
        )
        or not timing["latency_p50_ms"] <= timing["latency_p95_ms"] <= timing["latency_p99_ms"]
    ):
        raise ValueError("HTTP latency sample is invalid.")


def create(
    image_id,
    bundle,
    pin,
    scratch,
    *,
    profile=None,
    reference=None,
    bad_pin=False,
    missing=False,
    corrupt=None,
):
    name = "recsys-qualification-" + uuid.uuid4().hex[:16]
    args = [
        "container",
        "create",
        "--name",
        name,
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--user",
        "10001:10001",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--memory-swap",
        "4g",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777",
        "--stop-timeout",
        "30",
        "--env",
        "RECSYS_MANIFEST_SHA256=" + ("0" * 64 if bad_pin else pin),
    ]
    if not missing:
        args += ["--mount", f"type=bind,source={bundle},target=/model,readonly"]
    if reference:
        directory, ref_pin = reference
        args += [
            "--mount",
            f"type=bind,source={directory},target=/reference,readonly",
            "--env",
            "RECSYS_NUMERIC_REFERENCE_SHA256=" + ref_pin,
        ]
    if corrupt:
        args += ["--mount", f"type=bind,source={corrupt},target=/model/weights.npy,readonly"]
    if profile:
        args += ["--no-healthcheck", "--entrypoint", "python"]
    args += [image_id]
    if profile:
        args += ["/opt/runtime/probe.py", profile]
    try:
        docker(args, scratch)
    except BaseException:
        remove(name, scratch)
        raise
    return name


def remove(name, scratch):
    # rm can report an already absent name; require independent daemon confirmation.
    docker(["container", "rm", "--force", name], scratch, timeout=30, check=False)
    remaining = docker(
        ["container", "ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
        scratch,
        timeout=30,
    )
    if remaining.stdout.strip():
        raise ValueError("Owned container remains after cleanup; no success receipt is allowed.")


def job(image_id, bundle, pin, scratch, profile, *, reference=None):
    name = create(image_id, bundle, pin, scratch, profile=profile, reference=reference)
    try:
        policy = validate_container(
            inspect("container", name, scratch), image_id, reference=reference is not None
        )
        docker(["container", "start", name], scratch)
        exit_code = docker(["container", "wait", name], scratch, timeout=240).stdout.strip()
        logs = docker(["container", "logs", name], scratch)
        data = json.loads(logs.stdout)
        if exit_code != "0":
            raise ValueError("Isolated qualification job failed; inspect private log.")
        return data, policy
    finally:
        remove(name, scratch)


def verify(bundle, pin, output):
    validate_context()
    bundle = Path(bundle).absolute()
    manifest = verify_inventory(bundle, pin)
    validate_quality(QUALITY_PATH, QUALITY_PIN, manifest, pin)
    source = sources()
    scratch = scratch_directory()
    started = datetime.now(timezone.utc).isoformat()
    engine = json.loads(docker(["info", "--format", "{{json .}}"], scratch).stdout)
    if engine.get("OSType") != "linux" or engine.get("Architecture") != "x86_64":
        raise ValueError("Qualification requires a Linux/amd64 engine.")
    context_evidence = verify_context(scratch)
    docker(
        [
            "build",
            "--platform",
            "linux/amd64",
            "--file",
            "containers/Dockerfile",
            "--tag",
            IMAGE,
            "--progress",
            "plain",
            ".",
        ],
        scratch,
        timeout=900,
    )
    image = inspect("image", IMAGE, scratch)
    image_id = validate_image(image)
    ref_directory = scratch / "reference"
    ref_pin = build_reference(bundle, pin, ref_directory)
    reference_metadata = json.loads((ref_directory / "metadata.json").read_text())
    runtime, _ = job(image_id, bundle, pin, scratch, "runtime")
    validate_runtime(runtime, manifest)
    model, limits = job(image_id, bundle, pin, scratch, "model", reference=(ref_directory, ref_pin))
    negative = {}
    corrupt = scratch / "corrupt-weights.npy"
    corrupt.write_bytes(b"not-the-pinned-weight-array")
    for kind in ("bad_pin", "missing", "corrupt"):
        options = {kind: corrupt if kind == "corrupt" else True}
        name = create(image_id, bundle, pin, scratch, **options)
        try:
            docker(["container", "start", name], scratch)
            code = docker(["container", "wait", name], scratch, timeout=90).stdout.strip()
            state = inspect("container", name, scratch)["State"]
            if (
                code == "0"
                or state.get("OOMKilled")
                or state.get("Health", {}).get("Status") == "healthy"
            ):
                raise ValueError("Invalid model was not rejected cleanly before readiness.")
            negative[kind] = True
        finally:
            remove(name, scratch)
    name = create(image_id, bundle, pin, scratch)
    try:
        limits = validate_container(inspect("container", name, scratch), image_id)
        launched = time.monotonic()
        docker(["container", "start", name], scratch)
        deadline = time.monotonic() + 150
        while True:
            state = inspect("container", name, scratch)["State"]
            if state["Status"] != "running" or time.monotonic() >= deadline:
                raise ValueError("Snapshot did not become healthy within its startup bound.")
            if state.get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(1)
        startup = time.monotonic() - launched
        docker(["container", "exec", name, "python", "-m", "pip", "check"], scratch)
        response = docker(
            ["container", "exec", name, "python", "/opt/runtime/probe.py", "http"],
            scratch,
            timeout=180,
        )
        http = json.loads(response.stdout)
        validate_evidence(model, http, pin, manifest["components"]["references.json"]["sha256"])
        docker(["container", "stop", "--time", "30", name], scratch, timeout=45)
        state = inspect("container", name, scratch)["State"]
        logs = docker(["container", "logs", name], scratch)
        events = [
            json.loads(line) for line in logs.stderr.splitlines() if line.startswith('{"event":')
        ]
        cleanup = sum(e["event"] == "cleanup_complete" for e in events)
        if (
            state["Running"]
            or state["OOMKilled"]
            or state["ExitCode"] not in (0, 143)
            or cleanup != 1
        ):
            raise ValueError("Container did not drain and stop cleanly.")
    finally:
        remove(name, scratch)
    validate_context()
    if (
        source != sources()
        or file_sha(ref_directory / "metadata.json") != ref_pin
        or file_sha(ref_directory / "numerics.npz") != reference_metadata["archive_sha256"]
    ):
        raise ValueError("Qualification source or numerical input changed.")
    verify_inventory(bundle, pin)
    refs = json.loads((bundle / "references.json").read_text())
    if http["outputs_sha256"] != digest(
        [{"items": r["trace"]["output"], "route": r["trace"]["route"]} for r in refs]
    ):
        raise ValueError("HTTP output digest belongs to another reference set.")
    result = {
        "schema_version": 1,
        "policy": POLICY,
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_passed": True,
        "deployment_eligible": False,
        "identity": {
            "files_sha256": source,
            "base_image": BASE,
            "image_id": image_id,
            "manifest_sha256": pin,
            "quality_receipt_sha256": QUALITY_PIN,
            "numeric_reference_metadata_sha256": ref_pin,
            "references_sha256": manifest["components"]["references.json"]["sha256"],
        },
        "engine": {
            k: engine.get(k)
            for k in ("ServerVersion", "OSType", "Architecture", "KernelVersion", "OperatingSystem")
        },
        "numeric_reference": reference_metadata,
        "runtime": runtime,
        "build_context": context_evidence,
        "container_cleanup_verified": True,
        "resource_policy": limits,
        "model": model,
        "http": http,
        "startup_to_healthy_seconds": startup,
        "negative_startup": negative,
        "graceful_cleanup_events": cleanup,
        "serving_rss_within_2gib": max(
            http["serving_rss_before_requests_bytes"], http["serving_rss_after_requests_bytes"]
        )
        <= 2 * 1024**3,
        "limits": [
            "Isolated Docker Desktop Linux/amd64; no published port or public exposure.",
            "Cross-platform policy approved after initial bitwise feature/score failure; old policy and references unchanged.",
            "Finite 101-reference default cache-off/busy-reject sample; not fresh quality, representative load or SLA.",
            "4GiB cgroup cap does not waive the 2GiB RSS target. Cgroup peak includes operator probes/cache.",
            "Pinned inputs and local image content ID; not a bit-for-bit image rebuild or a published registry digest.",
        ],
    }
    publish(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Preserve completed receipts; choose a new output path.")
    try:
        verify(args.bundle, args.manifest_sha256, args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(
            1, "Linux qualification failed; no success receipt published. Inspect private logs.\n"
        )
    print(
        json.dumps(
            {
                "qualification_passed": True,
                "deployment_eligible": False,
                "output": args.output.as_posix(),
            }
        )
    )


if __name__ == "__main__":
    main()
