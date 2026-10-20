"""Assess a fixed HTTP workload on the unchanged isolated Linux snapshot image."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, file_sha

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import http_capacity_workload as workload  # noqa: E402
from scripts import snapshot_release as release  # noqa: E402
from scripts import verify_linux_container as linux  # noqa: E402
from scripts.release_validation import load_receipt  # noqa: E402
from scripts.verify_release import publish  # noqa: E402

QUALIFICATION = ROOT / "benchmarks/containers/linux_snapshot_boundary_validation_v1.json"
QUALIFICATION_PIN = "cdc11edf294a5ddd3d707fe7c3c565b2f53db1e0d5ecb43712174bddb05637ec"
RELEASE_EVIDENCE = ROOT / "benchmarks/release/release_workflow_preflight_validation_v1.json"
RELEASE_PIN = "7b37d58c41c34cc7011adcf3c0ed39e29512aaf91b1a97b893a689bbde86d55d"
FILES = (
    "scripts/http_capacity_workload.py",
    "scripts/benchmark_http_capacity.py",
    "tests/unit/test_http_capacity.py",
    "tests/integration/test_capacity_process.py",
)


def source_identity():
    return {name: file_sha(ROOT / name) for name in FILES}


def verify_cell(result, cell):
    workload.validate_mix()
    summary = result.get("summary", {})
    offered = workload.POLICY["duration_seconds"] * cell["rate"]
    if (
        result.get("cell") != cell
        or result.get("parity_passed") is not True
        or result.get("pre_references") != 101
        or result.get("post_references") != 101
        or type(summary.get("offered")) is not int
        or summary["offered"] != offered
        or type(summary.get("attempted")) is not int
        or not 0 <= summary["attempted"] <= offered
        or summary.get("client_shed") != offered - summary["attempted"]
        or summary.get("completed_http") != summary["attempted"]
        or sum(summary.get("status_counts", {}).values()) != summary["attempted"]
        or summary.get("successes") != summary.get("status_counts", {}).get("200", 0)
        or sum(result.get("offered_cohorts", {}).values()) != offered
        or result.get("offered_cohorts") != {"warm": offered * 4 // 5, "cold": offered // 5}
        or result.get("offered_k")
        != {"20": offered * 3 // 5, "10": offered // 5, "5": offered // 5}
        or type(result.get("cgroup_memory_peak_bytes")) is not int
        or not 0 < result["cgroup_memory_peak_bytes"] <= linux.MEMORY
        or not isinstance(summary.get("targets_met"), bool)
        or summary["targets_met"] != all(summary.get("targets", {}).values())
    ):
        raise ValueError("Incomplete or inconsistent capacity cell.")
    if not summary.get("targets") or summary["resources"]["samples"] < 100:
        raise ValueError("Missing target/resource evidence.")
    validate_summary(summary)
    workload.validate_measurement(
        summary, cell, result["offered_cohorts"], result["offered_k"], result.get("telemetry_delta")
    )
    if not re.fullmatch(r"[0-9a-f]{64}", result.get("request_sequence_sha256", "")):
        raise ValueError("Missing request-sequence identity.")
    return result


def validate_summary(summary):
    counts = summary["status_counts"]
    if not set(counts) <= {"200", "429", "503"} or any(
        type(v) is not int or v < 0 for v in counts.values()
    ):
        raise ValueError("Invalid workload outcome counts.")
    for key in ("successes", "client_shed", "completed_http"):
        if type(summary[key]) is not int or summary[key] < 0:
            raise ValueError("Capacity counts must be nonnegative integers.")
    timing_keys = {
        "latency_samples",
        "latency_avg_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
    }
    timings = [
        summary["dispatch"],
        *(
            row[scope]
            for row in summary["latency"].values()
            for scope in ("http", "schedule_to_end")
        ),
    ]
    for timing in timings:
        if (
            set(timing) != timing_keys
            or type(timing["latency_samples"]) is not int
            or timing["latency_samples"] < 0
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0
                for k, v in timing.items()
                if k != "latency_samples"
            )
        ):
            raise ValueError("Invalid latency evidence.")
        if not timing["latency_p50_ms"] <= timing["latency_p95_ms"] <= timing["latency_p99_ms"]:
            raise ValueError("Latency percentiles are unordered.")
    warm = summary["latency"]["warm_success"]["http"]
    cold = summary["latency"]["cold_success"]["http"]
    if (
        warm["latency_samples"] + cold["latency_samples"] != summary["successes"]
        or summary["dispatch"]["latency_samples"] != summary["attempted"]
    ):
        raise ValueError("Latency denominators differ from outcomes.")
    resources = summary["resources"]
    if (
        type(resources["rss_max_bytes"]) is not int
        or not 0 < resources["rss_max_bytes"] < 2**63
        or type(resources["samples"]) is not int
    ):
        raise ValueError("Invalid resource sample evidence.")
    limits = workload.POLICY["targets"]
    expected = {
        "enough_warm_successes": warm["latency_samples"] >= limits["minimum_warm_successes"],
        "warm_http_p95": bool(warm["latency_samples"])
        and warm["latency_p95_ms"] <= limits["warm_p95_ms"],
        "warm_http_p99": bool(warm["latency_samples"])
        and warm["latency_p99_ms"] <= limits["warm_p99_ms"],
        "rss": resources["rss_max_bytes"] <= limits["rss_bytes"],
        "errors": summary["transport_error_fraction"] <= limits["error_fraction"],
        "rejections": summary["rejection_fraction"] <= limits["rejection_fraction"],
        "driver_adequate": bool(summary["attempted"])
        and summary["dispatch"]["latency_p99_ms"] <= limits["dispatch_p99_ms"],
    }
    if summary["targets"] != expected or any(
        type(v) is not bool for v in summary["targets"].values()
    ):
        raise ValueError("Capacity target classification differs from measured evidence.")
    expected_fraction = (
        counts.get("429", 0) + counts.get("503", 0) + summary["client_shed"]
    ) / summary["offered"]
    if (
        summary["rejection_fraction"] != expected_fraction
        or summary["transport_error_fraction"] != 0
    ):
        raise ValueError("Capacity outcome fractions differ from complete measurement.")


class CapacityBackend(release.DockerBackend):
    """Reuse release ownership/cleanup; only the explicit cache CLI settings differ."""

    def __init__(self, root, bundle, scope, cached):
        super().__init__(root, bundle, scope)
        self.cached = cached
        self.command = ["--bundle-path", "/model", "--port", "8000"]
        if cached:
            cache = workload.POLICY["cache"]
            self.command += [
                "--cache-max-entries",
                str(cache["entries"]),
                "--cache-max-bytes",
                str(cache["bytes"]),
                "--cache-ttl-seconds",
                str(cache["ttl_seconds"]),
            ]

    def call(self, args, **kwargs):
        if args[0] == "create":
            args = [*args, *self.command]
        if "input" in kwargs:
            result = subprocess.run(
                ["docker", "container", *args],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                **kwargs,
            )
            with (self.logs / "docker.log").open("a", encoding="utf-8") as stream:
                stream.write(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError("Capacity driver failed; inspect private container log.")
            return result
        return super().call(args, **kwargs)

    def owned(self, entry, descriptor):
        state = linux.inspect("container", entry["container_name"], self.logs)
        config = state["Config"]
        labels = config.get("Labels") or {}
        env = dict(value.split("=", 1) for value in config["Env"])
        if (
            labels.get("recsys.release.scope") != self.scope
            or labels.get("recsys.release.id") != descriptor["release_id"]
            or state["Name"] != "/" + entry["container_name"]
            or (entry.get("container_id") is not None and entry["container_id"] != state["Id"])
            or config["Cmd"] != self.command
            or config["Entrypoint"] != ["python", "-m", "ecommerce_recsys.serving"]
            or env.get("RECSYS_MANIFEST_SHA256") != descriptor["manifest_sha256"]
            or any(key.startswith("RECSYS_API_TOKEN") for key in env)
        ):
            raise ValueError("Capacity container ownership/command/environment differs.")
        linux.validate_container(state, descriptor["image_id"])
        return state


def machine_identity(scratch):
    response = linux.docker(["info", "--format", "{{json .}}"], scratch)
    info = json.loads(response.stdout)
    if info.get("OSType") != "linux" or info.get("Architecture") != "x86_64":
        raise ValueError("Capacity assessment requires Linux/amd64 Docker.")
    return {
        key: info[key]
        for key in (
            "OSType",
            "Architecture",
            "NCPU",
            "MemTotal",
            "KernelVersion",
            "ServerVersion",
            "OperatingSystem",
        )
    }


def run_cell(cell, bundle, evidence, scratch):
    scope = digest({"scratch": str(scratch.resolve()), "cell": cell})
    name = "recsys-release-" + scope[:12] + "-" + uuid.uuid4().hex[:12]
    backend = CapacityBackend(scratch, bundle, scope, cell["cached"])
    descriptor = {
        "release_id": cell["name"],
        "image_id": evidence["identity"]["image_id"],
        "manifest_sha256": evidence["identity"]["manifest_sha256"],
    }
    entry = {"container_name": name, "container_id": None}
    journal = scratch / "owned.json"
    release.atomic(journal, {"entry": entry, "descriptor": descriptor, "scope": scope})
    result = None
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    try:
        entry["container_id"] = backend.create(entry, descriptor)
        release.atomic(journal, {"entry": entry, "descriptor": descriptor, "scope": scope})
        backend.start(entry, descriptor)
        deadline = time.monotonic() + 150
        while not backend.healthy(entry, descriptor):
            if (
                time.monotonic() >= deadline
                or not backend.owned(entry, descriptor)["State"]["Running"]
            ):
                raise ValueError("Capacity worker did not become ready.")
            time.sleep(1)
        startup = time.perf_counter() - started
        code = (ROOT / "scripts/http_capacity_workload.py").read_text(encoding="utf-8")
        response = backend.call(
            [
                "exec",
                "-i",
                name,
                "python",
                "-",
                "--cell",
                cell["name"],
                "--manifest-sha256",
                descriptor["manifest_sha256"],
            ],
            input=code,
            timeout=600,
        )
        result = verify_cell(json.loads(response.stdout), cell)
        result["startup_to_docker_healthy_seconds"] = startup
    finally:
        # Journal remains if ownership/removal cannot be confirmed; never publish success.
        cleanup = backend.remove(entry, descriptor, graceful=result is not None)
        if result is not None and (
            cleanup.get("graceful") is not True
            or type(cleanup.get("cleanup_events")) is not int
            or cleanup.get("cleanup_events") != 1
            or cleanup.get("prior_already_exited_abnormally") is not False
        ):
            raise ValueError("Capacity cell did not prove owned graceful cleanup.")
        journal.unlink()
    return {
        **result,
        "cleanup": cleanup,
        "started_utc": started_utc,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }


def checkpoint_identity(bundle, pin, source, machine):
    return {
        "files_sha256": source,
        "policy_sha256": digest({"policy": workload.POLICY, "cells": workload.CELLS}),
        "manifest_sha256": pin,
        "bundle_path": str(bundle.resolve()),
        "qualification_sha256": file_sha(QUALIFICATION),
        "release_evidence_sha256": file_sha(RELEASE_EVIDENCE),
        "controller_files_lf_sha256": release.code_identity(),
        "machine": machine,
    }


def load_progress(path, identity):
    workload.validate_mix()
    if path.is_symlink():
        raise ValueError("Capacity checkpoint cannot be a symlink.")
    if not path.exists():
        return {"identity": identity, "cells": []}
    saved = load_receipt(path)
    if saved.get("identity") != identity or not isinstance(saved.get("cells"), list):
        raise ValueError("Capacity checkpoint identity differs.")
    if len(saved["cells"]) > len(workload.CELLS):
        raise ValueError("Too many checkpoint cells.")
    for index, row in enumerate(saved["cells"]):
        verify_cell(row, workload.CELLS[index])
        if (
            row.get("cleanup", {}).get("graceful") is not True
            or type(row["cleanup"].get("cleanup_events")) is not int
            or row["cleanup"].get("cleanup_events") != 1
            or row["cleanup"].get("removed") is not True
            or row["cleanup"].get("prior_already_exited_abnormally") is not False
        ):
            raise ValueError("Checkpoint cleanup proof differs.")
    return {"identity": identity, "cells": saved["cells"]}


def verify(bundle, manifest_pin, output, work_root):
    workload.validate_mix()
    bundle, output, work_root = Path(bundle).resolve(), Path(output), Path(work_root).resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("Preserve completed capacity receipts; choose a new path.")
    work_root.mkdir(parents=True, exist_ok=True)
    with release.operation_lock(work_root):
        # This pin is fixed in source before the first measurement.
        evidence, _ = release.qualification(QUALIFICATION, QUALIFICATION_PIN, bundle)
        if manifest_pin != evidence["identity"]["manifest_sha256"]:
            raise ValueError("Capacity manifest differs from qualified identity.")
        if file_sha(RELEASE_EVIDENCE) != RELEASE_PIN:
            raise ValueError("Pinned M22 release evidence differs.")
        previous = load_receipt(RELEASE_EVIDENCE)
        if (
            previous.get("operational_passed") is not True
            or previous["identity"]["files_lf_sha256"] != release.code_identity()
        ):
            raise ValueError("Capacity assessment requires unchanged M22 release source/evidence.")
        source = source_identity()
        machine = machine_identity(work_root)
        identity = checkpoint_identity(bundle, manifest_pin, source, machine)
        progress_path = work_root / "checkpoint.json"
        progress = load_progress(progress_path, identity)
        if any(work_root.glob("*/owned.json")):
            raise ValueError("Interrupted capacity ownership requires explicit inspection/cleanup.")
        started = datetime.now(timezone.utc).isoformat()
        for cell in workload.CELLS[len(progress["cells"]) :]:
            scratch = work_root / cell["name"]
            scratch.mkdir(exist_ok=True)
            result = run_cell(cell, bundle, evidence, scratch)
            if (
                source_identity() != source
                or checkpoint_identity(bundle, manifest_pin, source, machine_identity(work_root))
                != identity
            ):
                raise ValueError("Capacity source/input/machine changed while measured.")
            progress["cells"].append(result)
            release.atomic(progress_path, progress)
            print(
                json.dumps(
                    {
                        "completed_cell": cell["name"],
                        "targets_met": result["summary"]["targets_met"],
                    }
                ),
                flush=True,
            )
        release.qualification(QUALIFICATION, QUALIFICATION_PIN, bundle)
        if source_identity() != source:
            raise ValueError("Capacity source changed before publication.")
        if (
            progress["cells"][1]["request_sequence_sha256"]
            != progress["cells"][2]["request_sequence_sha256"]
        ):
            raise ValueError("Matched-rate cache controls used different request sequences.")
        result = {
            "schema_version": 1,
            "assessment": workload.POLICY["version"],
            "assessment_completed": True,
            "functional_parity_passed": True,
            "deployment_eligible": False,
            "started_utc": progress["cells"][0]["started_utc"],
            "invocation_started_utc": started,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "identity": {
                **{key: value for key, value in identity.items() if key != "bundle_path"},
                "image_id": evidence["identity"]["image_id"],
            },
            "policy": workload.POLICY,
            "cells": progress["cells"],
            "all_cell_targets_met": all(row["summary"]["targets_met"] for row in progress["cells"]),
            "limits": [
                "Constructed 100 warm/one cold snapshot contexts, repeated requests; not observed production traffic or new model quality.",
                "Driver and service share a 2CPU/4GiB Docker Desktop Linux cgroup, network none; timings exclude external networks.",
                "Primed cache is an explicit repeat-traffic benefit scenario; no production hit-rate or default-cache adoption claim.",
                "Security quotas unchanged; 8rps intentionally exceeds the single-peer refill budget.",
                "150-second cells assess only this finite grid; sustained/failure/load and native target-host qualification remain separate.",
                "Performance targets do not replace memory, reliability or deployment gates. No public exposure or online evaluation.",
            ],
        }
        publish(output, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.bundle, args.manifest_sha256, args.output, args.work_root)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        parser.exit(
            1, "Capacity assessment failed; inspect private checkpoint/owned journal/logs.\n"
        )


if __name__ == "__main__":
    main()
