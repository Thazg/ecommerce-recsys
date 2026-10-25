"""Compare isolated original/indexed readers against every sealed model reference."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
POLICY = {
    "readers": ["original", "compact"],
    "reference_requests": 101,
    "warm_requests": 100,
    "cold_requests": 1,
    "parity": "exact full pool, evidence, feature/score digests, route and output",
    "sample_interval_seconds": 0.05,
    "sampling_scope": "external parent process plus explicit ready/final RSS snapshots",
    "maximum_sample_gap_seconds": 0.2,
    "worker_deadline_seconds": 240,
    "rss_target_bytes": 2 * 1024**3,
    "numeric_threads": 1,
    "scope": "local package reader; no HTTP, container or cloud qualification",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sources():
    paths = [
        *sorted((ROOT / "src/ecommerce_recsys").rglob("*.py")),
        Path(__file__).resolve(),
        ROOT / "tests/unit/test_compact_runtime.py",
        ROOT / "tests/unit/test_snapshot_memory.py",
    ]
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in paths
    }


def worker(reader, bundle_path, pin):
    process = psutil.Process()
    started = time.perf_counter()
    from ecommerce_recsys.artifacts import load_bundle
    from ecommerce_recsys.artifacts.contract import environment

    if reader == "compact":
        from ecommerce_recsys.artifacts.compact_runtime import load_compact_bundle

        loader = load_compact_bundle
    else:
        loader = load_bundle
    bundle = loader(bundle_path, expected_manifest_sha256=pin)
    gc.collect()
    ready = process.memory_info().rss
    ready_at = time.perf_counter()
    load_seconds = ready_at - started
    records = json.loads((bundle_path / "references.json").read_text(encoding="utf-8"))
    if not isinstance(records, list) or len(records) != POLICY["reference_requests"]:
        raise ValueError("The complete 101-reference snapshot is required.")
    users, timings = set(), {"warm": [], "cold": []}
    for record in records:
        user = record["user_id"]
        if user in users or (user is not None and user not in bundle.user_index):
            raise ValueError("Duplicate or non-snapshot reference context.")
        users.add(user)
        started = time.perf_counter()
        if bundle.trace(user) != record["trace"]:
            raise ValueError("Exact sealed reference trace differs.")
        timings["cold" if user is None else "warm"].append(time.perf_counter() - started)
    if None not in users or len(users) - 1 != POLICY["warm_requests"]:
        raise ValueError("Reference warm/cold coverage differs.")
    gc.collect()
    time.sleep(0.25)
    after = process.memory_info().rss
    return {
        "reader": reader,
        "manifest_sha256": pin,
        "runtime": {**environment(), "psutil": psutil.__version__},
        "parity_passed": True,
        "reference_requests": len(records),
        "warm_requests": len(timings["warm"]),
        "cold_requests": len(timings["cold"]),
        "load_seconds_including_imports": load_seconds,
        "ready_rss_bytes": ready,
        "after_references_rss_bytes": after,
        "ready_at": ready_at,
        "finished_at": time.perf_counter(),
        "reference_trace_seconds": {key: sum(value) for key, value in timings.items()},
    }


def validate_result(value, reader, pin):
    if (
        not isinstance(value, dict)
        or value.get("reader") != reader
        or value.get("manifest_sha256") != pin
        or value.get("parity_passed") is not True
        or not isinstance(value.get("runtime"), dict)
    ):
        raise ValueError("Reader result identity or parity differs.")
    for field in ("reference_requests", "warm_requests", "cold_requests"):
        if type(value.get(field)) is not int or value[field] != POLICY[field]:
            raise ValueError("Incomplete reference coverage.")
    for field in (
        "ready_rss_bytes",
        "after_references_rss_bytes",
        "load_peak_rss_bytes",
        "inference_peak_rss_bytes",
        "sampled_peak_rss_bytes",
        "sample_count",
    ):
        if type(value.get(field)) is not int or value[field] <= 0:
            raise ValueError("Invalid resource sample.")
    for field in (
        "load_seconds_including_imports",
        "sample_span_seconds",
        "maximum_sample_gap_seconds",
    ):
        number = value.get(field)
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            raise ValueError("Invalid measurement duration.")
    if (
        value["maximum_sample_gap_seconds"] > POLICY["maximum_sample_gap_seconds"]
        or value["sample_count"] < 2
        or value["sample_span_seconds"] > POLICY["worker_deadline_seconds"]
        or value["sample_span_seconds"]
        > (value["sample_count"] - 1) * value["maximum_sample_gap_seconds"] + 1e-6
        or value["sampled_peak_rss_bytes"]
        != max(value["load_peak_rss_bytes"], value["inference_peak_rss_bytes"])
        or value["load_peak_rss_bytes"] < value["ready_rss_bytes"]
        or value["inference_peak_rss_bytes"]
        < max(value["ready_rss_bytes"], value["after_references_rss_bytes"])
    ):
        raise ValueError("Inconsistent resource scope or coverage.")
    times = value.get("reference_trace_seconds")
    if (
        not isinstance(times, dict)
        or set(times) != {"warm", "cold"}
        or any(
            type(t) not in (int, float) or not math.isfinite(t) or t <= 0 for t in times.values()
        )
    ):
        raise ValueError("Incomplete reference timing scope.")
    if sum(times.values()) > value["sample_span_seconds"]:
        raise ValueError("Reference timing exceeds the measured process span.")


def run_reader(reader, path, pin):
    env = {
        **os.environ,
        **dict.fromkeys(("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"), "1"),
    }
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        reader,
        "--bundle",
        str(path),
        "--manifest-sha256",
        pin,
    ]
    started = time.perf_counter()
    child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    samples, errors = [], []
    stop = threading.Event()
    sampler = None

    def sample():
        try:
            while not stop.is_set():
                samples.append((time.perf_counter(), handle.memory_info().rss))
                stop.wait(POLICY["sample_interval_seconds"])
        except psutil.NoSuchProcess:
            if child.poll() is None:
                errors.append("sampling_process_disappeared")
        except Exception:
            errors.append("resource_sampling_failed")

    try:
        handle = psutil.Process(child.pid)
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        stdout, _ = child.communicate(timeout=POLICY["worker_deadline_seconds"])
    except BaseException:
        if child.poll() is None:
            child.kill()
        child.communicate()
        raise
    finally:
        stop.set()
        if sampler is not None and sampler.ident is not None:
            sampler.join(timeout=5)
    if child.returncode != 0:
        raise ValueError(f"{reader} verification worker failed; no receipt published.")
    if sampler.is_alive() or errors or len(samples) < 2:
        raise ValueError("Complete external resource sampling failed.")
    result = json.loads(stdout)
    ready_at, finished_at = result.pop("ready_at"), result.pop("finished_at")
    if not started < ready_at < finished_at <= time.perf_counter():
        raise ValueError("Worker stage timestamps differ from the owned process.")
    if (
        samples[0][0] - started > POLICY["maximum_sample_gap_seconds"]
        or finished_at - samples[-1][0] > POLICY["maximum_sample_gap_seconds"]
    ):
        raise ValueError("Incomplete resource sampling coverage.")
    samples.extend(
        [(ready_at, result["ready_rss_bytes"]), (finished_at, result["after_references_rss_bytes"])]
    )
    samples.sort()
    load_peak = max(rss for stamp, rss in samples if stamp <= ready_at)
    inference_peak = max(
        result["ready_rss_bytes"], *(rss for stamp, rss in samples if stamp >= ready_at)
    )
    result.update(
        {
            "load_peak_rss_bytes": load_peak,
            "inference_peak_rss_bytes": inference_peak,
            "sampled_peak_rss_bytes": max(load_peak, inference_peak),
            "sample_count": len(samples),
            "sample_span_seconds": samples[-1][0] - samples[0][0],
            "maximum_sample_gap_seconds": max(b[0] - a[0] for a, b in zip(samples, samples[1:])),
        }
    )
    validate_result(result, reader, pin)
    return result


def assess(path, pin):
    before = sources()
    original, compact = [run_reader(reader, path, pin) for reader in POLICY["readers"]]
    if before != sources() or original["runtime"] != compact["runtime"]:
        raise ValueError("Source or environment changed during the paired assessment.")
    return assessment(original, compact, pin, before)


def assessment(original, compact, pin, identity):
    for reader, value in zip(POLICY["readers"], (original, compact), strict=True):
        validate_result(value, reader, pin)
    if original["runtime"] != compact["runtime"]:
        raise ValueError("Paired runtime identity differs.")
    result = {
        "schema_version": 1,
        "verification": "snapshot-memory-profile-v1",
        "policy": POLICY,
        "sources_sha256_lf": identity,
        "manifest_sha256": pin,
        "results": [original, compact],
        "ready_rss_reduction_bytes": original["ready_rss_bytes"] - compact["ready_rss_bytes"],
        "compact_loaded_memory_target_passed": compact["inference_peak_rss_bytes"]
        <= POLICY["rss_target_bytes"],
        "compact_startup_peak_within_target": compact["load_peak_rss_bytes"]
        <= POLICY["rss_target_bytes"],
        "same_host_exact_parity": True,
        "workers_exited": True,
        "quality_recomputed": False,
        "http_measured": False,
        "linux_qualified": False,
        "deployment_eligible": False,
    }
    return {**result, "content_sha256": digest(result)}


def check_receipt(bundle_path, pin, path):
    from ecommerce_recsys.artifacts.contract import verify_inventory

    verify_inventory(bundle_path, pin)
    if path.is_symlink() or path.stat().st_size > 1024**2:
        raise ValueError("Invalid memory receipt file.")

    def unique_fields(pairs):
        fields = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError("Duplicate memory receipt field.")
            fields[key] = value
        return fields

    saved = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
    results = saved.get("results") if isinstance(saved, dict) else None
    if not isinstance(results, list) or len(results) != 2:
        raise ValueError("Both reader results are required.")
    expected = assessment(*results, pin, sources())
    if digest(saved) != digest(expected):
        raise ValueError("Memory receipt is stale or inconsistent.")
    return expected


def validate_output_path(path):
    if (
        any(part.is_symlink() for part in (path, *path.parents))
        or not path.parent.is_dir()
        or path.suffix != ".json"
    ):
        raise ValueError("Use a fresh JSON path in an existing directory.")


def publish(path, result):
    validate_output_path(path)
    if result.get("content_sha256") != digest(
        {k: v for k, v in result.items() if k != "content_sha256"}
    ):
        raise ValueError("Receipt is not sealed.")
    fd, name = tempfile.mkstemp(prefix=".memory-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--worker", choices=POLICY["readers"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{64}", args.manifest_sha256):
        parser.error("Provide a trusted lowercase manifest SHA-256.")
    try:
        if args.worker:
            if args.output or args.check:
                raise ValueError("Internal workers cannot publish receipts.")
            print(json.dumps(worker(args.worker, args.bundle.resolve(), args.manifest_sha256)))
            return
        if args.check:
            check_receipt(args.bundle.resolve(), args.manifest_sha256, args.check)
            print(json.dumps({"receipt_integrity_passed": True, "model_loaded": False}))
            return
        if args.output is None or args.output.exists() or args.output.is_symlink():
            raise ValueError("Provide an unused --output path.")
        validate_output_path(args.output)
        result = assess(args.bundle.resolve(), args.manifest_sha256)
        publish(args.output, result)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"Memory verification failed: {error}\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "same_host_exact_parity",
                    "ready_rss_reduction_bytes",
                    "compact_loaded_memory_target_passed",
                    "deployment_eligible",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
