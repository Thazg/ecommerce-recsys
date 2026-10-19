"""Operator-only verification inside the isolated Linux network namespace."""

from __future__ import annotations

import argparse
import http.client
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
from pathlib import Path
from time import monotonic, perf_counter, sleep

import psutil

import ecommerce_recsys
from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.contract import digest, environment, file_sha, runtime_code
from ecommerce_recsys.evaluation.latency import latency_metrics

if __package__:
    from .qualification import POLICY, capture, compare_arrays, exact_differences, open_reference
else:
    from qualification import POLICY, capture, compare_arrays, exact_differences, open_reference


def runtime():
    package = Path(ecommerce_recsys.__file__).parent
    return {
        "uid": os.geteuid(),
        "gid": os.getegid(),
        "system": platform.system(),
        "machine": platform.machine(),
        "numeric": environment(),
        "reader_runtime_code_sha256": runtime_code(),
        "packages": {
            d.metadata["Name"].lower().replace("_", "-"): d.version
            for d in importlib.metadata.distributions()
        },
        "package_sources_sha256": {
            p.relative_to(package).as_posix(): file_sha(p) for p in sorted(package.rglob("*.py"))
        },
        "scripts_available": importlib.util.find_spec("scripts") is not None,
        "training_directories_present": any(
            Path(p).exists() for p in ("/data", "/opt/app/data", "/build", "/opt/app/.git")
        ),
        "compiler_or_git_present": any(shutil.which(p) for p in ("gcc", "g++", "git")),
        "probe_sources_sha256": {p.name: file_sha(p) for p in Path(__file__).parent.glob("*.py")},
        "runtime_lock_sha256": file_sha(Path(__file__).parent / "runtime.lock"),
    }


def model():
    pin = os.environ["RECSYS_MANIFEST_SHA256"]
    started = perf_counter()
    bundle = load_bundle(Path("/model"), expected_manifest_sha256=pin)
    loaded = perf_counter() - started
    records = json.loads(Path("/model/references.json").read_text())
    reference_sha = file_sha(Path("/model/references.json"))
    arrays, metadata = open_reference(
        "/reference", os.environ["RECSYS_NUMERIC_REFERENCE_SHA256"], pin, reference_sha
    )
    mismatches, bitwise_mismatches = [], []
    errors = {
        name: {"max_abs_error": 0.0, "max_error_over_allowed": 0.0}
        for name in ("features", "scores")
    }
    try:
        if (
            metadata["reference_order_sha256"] != digest([r["user_id"] for r in records])
            or len(records) != 101
        ):
            raise ValueError("Numerical reference order or count differs.")
        for i, row in enumerate(records):
            actual, observed = capture(bundle, row["user_id"])
            fields = exact_differences(actual, row["trace"])
            bit_fields = [key for key in actual if actual[key] != row["trace"].get(key)]
            if bit_fields:
                bitwise_mismatches.append({"reference_index": i, "fields": sorted(bit_fields)})
            for name, array in zip(("features", "scores"), observed, strict=True):
                check = compare_arrays(array, arrays[f"{i:03}_{name}"])
                if not check["passed"]:
                    fields.append(name + "_numeric_bound")
                for key in errors[name]:
                    errors[name][key] = max(errors[name][key], check[key])
            if fields:
                mismatches.append({"reference_index": i, "fields": sorted(fields)})
    finally:
        arrays.close()
    return {
        "manifest_sha256": pin,
        "references_sha256": file_sha(Path("/model/references.json")),
        "references": len(records),
        "warm_references": sum(r["trace"]["route"] == "hybrid_learned" for r in records),
        "cold_references": sum(r["trace"]["route"] == "recent_popularity" for r in records),
        "policy": POLICY,
        "qualification_passed": not mismatches,
        "bitwise_parity": not bitwise_mismatches,
        "bitwise_mismatches": bitwise_mismatches,
        "array_errors": errors,
        "mismatches": mismatches,
        "load_seconds": loaded,
        "rss_after_references_bytes": psutil.Process().memory_info().rss,
        "reference_order_sha256": digest([r["user_id"] for r in records]),
    }


def http_probe():
    manifest = json.loads(Path("/model/model_manifest.json").read_text())
    records = json.loads(Path("/model/references.json").read_text())
    ids, times, outputs = set(), [], []
    last = 0.0

    def call(method, path, body=None, *, status=200, extra=None):
        nonlocal last
        if method == "POST":
            sleep(max(0, 0.26 - (monotonic() - last)))
            last = monotonic()
        headers = {"Content-Type": "application/json", **(extra or {})}
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
        connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=15)
        try:
            started = perf_counter()
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            raw = response.read(65537)
            elapsed = perf_counter() - started
            if response.status != status or len(raw) > 65536:
                raise ValueError("HTTP status or response budget differs.")
            value = json.loads(raw)
            request_id = response.getheader("X-Request-ID")
            if (
                not re.fullmatch("[0-9a-f]{32}", request_id or "")
                or request_id in ids
                or value.get("request_id") != request_id
                or response.getheader("Cache-Control") != "no-store"
                or response.getheader("X-Content-Type-Options") != "nosniff"
            ):
                raise ValueError("HTTP identity/security envelope differs.")
            ids.add(request_id)
            return value, elapsed
        finally:
            connection.close()

    def check(row, k=20):
        value, elapsed = call("POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k})
        if (
            value["items"] != row["trace"]["output"][:k]
            or value["route"] != row["trace"]["route"]
            or value["bundle_version"] != manifest["bundle_version"]
            or value["cutoff"] != manifest["snapshot"]["cutoff"]
            or value["manifest_sha256"] != os.environ["RECSYS_MANIFEST_SHA256"]
            or value["degraded"] is not False
            or value["cache_status"] != "disabled"
        ):
            raise ValueError("HTTP reference output or lineage differs.")
        return elapsed

    ready, _ = call("GET", "/health/ready")
    if ready["state"] != "ready" or ready["primary_calls"] != 0:
        raise ValueError("HTTP process is not a fresh ready worker.")
    rss_before = psutil.Process(1).memory_info().rss
    for row in records:
        elapsed = check(row)
        if row["trace"]["route"] == "hybrid_learned":
            times.append(elapsed)
        outputs.append({"items": row["trace"]["output"], "route": row["trace"]["route"]})
    warm = next(row for row in records if row["trace"]["route"] == "hybrid_learned")
    cold = next(row for row in records if row["user_id"] is None)
    for row in (warm, cold):
        for k in (1, 5, 10):
            check(row, k)
    check({"user_id": "unknown-linux-probe-context", "trace": cold["trace"]})
    denials = (
        ({"k": True}, 422, "validation_error", None),
        (b'{"k":1,"k":2}', 400, "invalid_json", None),
        (b"x" * 8193, 413, "body_too_large", None),
        ({}, 403, "forbidden_origin", {"Origin": "null"}),
    )
    for body, status, code, headers in denials:
        value, _ = call("POST", "/v1/recommendations", body, status=status, extra=headers)
        if value["error"]["code"] != code:
            raise ValueError("HTTP denial reason differs.")
    check(warm)
    final, _ = call("GET", "/health/ready")
    if final["state"] != "ready" or final["primary_calls"] != 109:
        raise ValueError("HTTP denial recovery/call ownership differs.")
    return {
        "warm_references": len(times),
        "cold_references": len(records) - len(times),
        "prefix_checks": 6,
        "unknown_cold_checks": 1,
        "denial_checks": len(denials),
        "recovery_checks": 1,
        "primary_calls": final["primary_calls"],
        "request_ids": len(ids),
        "exact_outputs": True,
        "outputs_sha256": digest(outputs),
        "pacing_seconds": 0.26,
        "warm_client_timing": latency_metrics(times),
        "serving_rss_before_requests_bytes": rss_before,
        "serving_rss_after_requests_bytes": psutil.Process(1).memory_info().rss,
        "cgroup_memory_peak_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text()),
        "cache_enabled": False,
        "busy_policy": "reject",
        "all_passed": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("runtime", "model", "http"))
    args = parser.parse_args()
    result = {"runtime": runtime, "model": model, "http": http_probe}[args.profile]()
    print(json.dumps(result, allow_nan=False))
    return 0 if args.profile != "model" or result["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
