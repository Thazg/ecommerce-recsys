"""Compare optional snapshot caching against uncached real loopback HTTP."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import digest, file_sha, runtime_code
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.serving.contracts import ServedRecommendationResponse

if __package__:
    from scripts.verify_recommendation_api import (
        ROOT,
        Probe,
        compare_output,
        implementation_identity,
        publish_receipt,
        reference_inputs,
        verify_openapi,
    )
else:
    from verify_recommendation_api import (
        ROOT,
        Probe,
        compare_output,
        implementation_identity,
        publish_receipt,
        reference_inputs,
        verify_openapi,
    )

EXPERIMENT = {
    "cache_entries": 256,
    "cache_entry_bytes": 1048576,
    "ttl_seconds": 300.0,
    "output_limit": 20,
    "prefix_limits": [5, 10],
    "prefix_warm_users": 3,
    "hit_p95_max_fraction_of_uncached": 0.5,
    "miss_p95_max_fraction_of_uncached": 1.25,
    "scope": "same pinned producer references; sequential loopback sample; no load/SLA/quality selection",
}


def code_identity():
    return {
        **implementation_identity(),
        "scripts/verify_service_cache.py": file_sha(Path(__file__)),
    }


def check_response(result, row, manifest, pin, k, cache_status):
    response = ServedRecommendationResponse.model_validate(result)
    if (
        response.cache_status != cache_status
        or response.degraded
        or response.manifest_sha256 != pin
    ):
        raise ValueError("Unexpected cache path, degraded state or manifest lineage.")
    base = {
        key: result[key] for key in ("request_id", "items", "route", "bundle_version", "cutoff")
    }
    return compare_output(base, row, manifest, k)


def benefit_gates(off, on):
    warm_p95 = off["warm"]["latency_p95_ms"]
    return {
        "hit_latency": on["hit_warm"]["latency_p95_ms"]
        <= EXPERIMENT["hit_p95_max_fraction_of_uncached"] * warm_p95,
        "miss_latency": on["miss_warm"]["latency_p95_ms"]
        <= EXPERIMENT["miss_p95_max_fraction_of_uncached"] * warm_p95,
    }


def run_phase(bundle, pin, manifest, references, *, enabled):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [
        sys.executable,
        "-m",
        "ecommerce_recsys.serving",
        "--bundle-path",
        str(bundle.resolve()),
        "--manifest-sha256",
        pin,
        "--port",
        str(port),
    ]
    if enabled:
        command += [
            "--cache-max-entries",
            str(EXPERIMENT["cache_entries"]),
            "--cache-max-bytes",
            str(EXPERIMENT["cache_entry_bytes"]),
            "--cache-ttl-seconds",
            str(EXPERIMENT["ttl_seconds"]),
            "--busy-policy",
            "recent_popularity",
        ]
    scratch = ROOT / ".local"
    scratch.mkdir(exist_ok=True)
    log_path = scratch / ("cache_http_on.log" if enabled else "cache_http_off.log")
    rss, stop = [], threading.Event()
    started = time.perf_counter()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        child = psutil.Process(process.pid)

        def sample():
            while not stop.is_set():
                try:
                    rss.append(child.memory_info().rss)
                except psutil.Error:
                    return
                stop.wait(0.05)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        probe = Probe(port)
        try:
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"HTTP startup failed; inspect {log_path}.")
                if time.perf_counter() - started > 180:
                    raise TimeoutError("HTTP startup deadline exceeded.")
                try:
                    ready, _ = probe.call("GET", "/health/ready")
                    break
                except OSError:
                    probe.close()
                    probe = Probe(port)
                    time.sleep(0.2)
            startup_seconds = time.perf_counter() - started
            ready_rss = child.memory_info().rss
            schema, _ = probe.call("GET", "/openapi.json")
            verify_openapi(schema)
            if (
                schema["info"]["version"] != "1.1.0"
                or ready["cache"]["enabled"] != enabled
                or ready["primary_calls"] != 0
            ):
                raise ValueError("Unexpected startup contract or cache configuration.")
            if (
                ready["bundle_version"] != manifest["bundle_version"]
                or ready["cutoff"] != manifest["snapshot"]["cutoff"]
                or ready["busy_policy"] != ("recent_popularity" if enabled else "reject")
            ):
                raise ValueError("Readiness reports a different model or overload policy.")
            if enabled and any(
                ready["cache"][key] != EXPERIMENT[value]
                for key, value in (
                    ("max_entries", "cache_entries"),
                    ("max_bytes", "cache_entry_bytes"),
                    ("ttl_seconds", "ttl_seconds"),
                )
            ):
                raise ValueError("Live cache settings differ from the prospective experiment.")
            warm = [r for r in references if r["trace"]["route"] == "hybrid_learned"]
            cold = next(r for r in references if r["trace"]["route"] == "recent_popularity")
            if not enabled:
                # Excluded warm-up does not prime an enabled cache.
                probe.call("POST", "/v1/recommendations", {"user_id": warm[0]["user_id"]})
            timings, outputs, snapshots = {}, [], []
            passes = ("miss", "hit") if enabled else ("disabled",)
            for path in passes:
                measured = {"warm": [], "cold": []}
                for row in references:
                    actual, elapsed = probe.call(
                        "POST",
                        "/v1/recommendations",
                        {"user_id": row["user_id"], "k": EXPERIMENT["output_limit"]},
                    )
                    output = check_response(actual, row, manifest, pin, 20, path)
                    if path != "hit":
                        outputs.append(output)
                    cohort = "warm" if row["trace"]["route"] == "hybrid_learned" else "cold"
                    measured[cohort].append(elapsed)
                for cohort, values in measured.items():
                    timings[f"{path}_{cohort}" if enabled else cohort] = latency_metrics(values)
                state, _ = probe.call("GET", "/health/ready")
                snapshots.append(state)
                if enabled and (
                    state["cache"]["entries"] > EXPERIMENT["cache_entries"]
                    or state["cache"]["charged_bytes"] > EXPERIMENT["cache_entry_bytes"]
                ):
                    raise ValueError("Cache exceeded the declared entry budget.")
            if enabled:
                for row in warm[: EXPERIMENT["prefix_warm_users"]]:
                    for k in EXPERIMENT["prefix_limits"]:
                        actual, _ = probe.call(
                            "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
                        )
                        check_response(actual, row, manifest, pin, k, "hit")
                for user in ("cache-probe-unknown-user", None):
                    actual, _ = probe.call("POST", "/v1/recommendations", {"user_id": user})
                    check_response(actual, cold, manifest, pin, 20, "hit")
            final, _ = probe.call("GET", "/health/ready")
            expected_calls = len(references) + (0 if enabled else 1)
            if final["primary_calls"] != expected_calls or final["fallback_calls"] != 0:
                raise ValueError("Reference pass made unexpected primary/fallback calls.")
            if enabled:
                expected_hits = len(references) + min(len(warm), 3) * 2 + 2
                if (
                    final["cache"]["misses"] != len(references)
                    or final["cache"]["hits"] != expected_hits
                    or final["cache"]["failures"]
                ):
                    raise ValueError("Cache path counters differ from the declared sequence.")
            final_rss = child.memory_info().rss
        finally:
            probe.close()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            stop.set()
            sampler.join(timeout=2)
    return {
        "timing": timings,
        "startup_seconds": startup_seconds,
        "schema_sha256": digest(schema),
        "ordered_outputs_sha256": digest(outputs),
        "ready": ready,
        "after_passes": snapshots,
        "final": final,
        "memory": {
            "ready_rss_bytes": ready_rss,
            "after_requests_rss_bytes": final_rss,
            "sampled_peak_rss_bytes": max(rss + [ready_rss, final_rss]),
            "charter_target_bytes": 2 * 1024**3,
            "observed_samples_within_target": max(rss + [ready_rss, final_rss]) <= 2 * 1024**3,
        },
    }


def verify(bundle, pin):
    manifest, references, reference_sha = reference_inputs(bundle, pin)
    source = code_identity()
    off = run_phase(bundle, pin, manifest, references, enabled=False)
    on = run_phase(bundle, pin, manifest, references, enabled=True)
    if source != code_identity() or off["ordered_outputs_sha256"] != on["ordered_outputs_sha256"]:
        raise ValueError("Source identity changed or paired outputs differ.")
    gates = benefit_gates(off["timing"], on["timing"])
    return {
        "schema_version": 1,
        "experiment": EXPERIMENT,
        "identity": {
            "manifest_sha256": pin,
            "references_sha256": reference_sha,
            "bundle_version": manifest["bundle_version"],
            "reader_runtime_code_sha256": runtime_code(),
            "files_sha256": source,
            "request_sequence_sha256": digest([r["user_id"] for r in references]),
        },
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("fastapi", "starlette", "uvicorn", "pydantic", "anyio", "psutil")
            },
        },
        "cache_off": off,
        "cache_on": on,
        "parity": {
            "reference_requests_per_pass": len(references),
            "warm_references": sum(r["trace"]["route"] == "hybrid_learned" for r in references),
            "cold_references": sum(r["trace"]["route"] == "recent_popularity" for r in references),
            "all_passed": True,
        },
        "benefit_gates": {**gates, "all_passed": all(gates.values())},
        "limits": [
            "Opt-in cache; no production hit-rate, workload SLO or independent quality evidence.",
            "One cold reference is not a latency distribution. Off has one excluded warm-up; on starts with empty cache.",
            "50ms process RSS sampling is a lower bound on peak; independent processes do not isolate cache allocation cost.",
            "Cache byte budget accounts stored entries, excluding fixed container/allocator costs; RSS is measured separately.",
            "Forced busy/failure semantics are verified in tests, including a fitted tiny snapshot; this probe does not force operational fallback.",
            "Probe processes are terminated after checks; graceful drain has deterministic test coverage.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve completed receipts; choose a new output path.")
    try:
        receipt = verify(args.bundle, args.manifest_sha256)
        publish_receipt(args.output, receipt)
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        parser.exit(1, f"Cache HTTP verification failed: {error}\n")
    print(
        json.dumps(
            {
                "parity": receipt["parity"],
                "benefit_gates": receipt["benefit_gates"],
                "cache_off": {
                    "timing": receipt["cache_off"]["timing"],
                    "memory": receipt["cache_off"]["memory"],
                },
                "cache_on": {
                    "timing": receipt["cache_on"]["timing"],
                    "memory": receipt["cache_on"]["memory"],
                    "cache": receipt["cache_on"]["final"]["cache"],
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
