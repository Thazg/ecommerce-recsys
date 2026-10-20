"""Bounded open-loop HTTP workload; also runs via stdin in the frozen Linux image."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

from ecommerce_recsys.evaluation.latency import latency_metrics

POLICY = {
    "version": "snapshot-http-capacity-v1",
    "duration_seconds": 150,
    "warm_fraction": 0.8,
    "k_mix": {"20": 0.6, "10": 0.2, "5": 0.2},
    "seed": 42,
    "arrival": "deterministic open-loop; no retries or hidden client queue",
    "connection": "one new loopback TCP connection per attempt",
    "reference_spacing_seconds": 0.26,
    "settle_seconds": 3,
    "timeout_seconds": 10,
    "sample_seconds": 0.05,
    "cache": {"entries": 256, "bytes": 1048576, "ttl_seconds": 900},
    "busy_policy": "reject",
    "security_rates": {"peer_rps": 5, "peer_burst": 10, "global_rps": 10, "global_burst": 20},
    "targets": {
        "warm_p95_ms": 300,
        "warm_p99_ms": 500,
        "rss_bytes": 2 * 1024**3,
        "error_fraction": 0.01,
        "rejection_fraction": 0.01,
        "dispatch_p99_ms": 10,
        "minimum_warm_successes": 100,
    },
}
CELLS = (
    {"name": "uncached-1rps", "rate": 1, "concurrency": 4, "cached": False},
    {"name": "uncached-4rps", "rate": 4, "concurrency": 8, "cached": False},
    {"name": "primed-cache-4rps", "rate": 4, "concurrency": 8, "cached": True},
    {"name": "primed-cache-8rps", "rate": 8, "concurrency": 16, "cached": True},
)


def validate_mix():
    """The published experiment supports one fixed, prospectively declared mix."""
    if (
        type(POLICY.get("warm_fraction")) not in (int, float)
        or POLICY["warm_fraction"] != 0.8
        or POLICY.get("k_mix") != {"20": 0.6, "10": 0.2, "5": 0.2}
        or any(type(v) not in (int, float) for v in POLICY["k_mix"].values())
    ):
        raise ValueError("Unsupported traffic mix; define a new schedule and experiment first.")


def sequence(references, count):
    validate_mix()
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValueError("Workload count must be a bounded positive integer.")
    warm = [row for row in references if row["trace"]["route"] == "hybrid_learned"]
    cold = [row for row in references if row["user_id"] is None]
    if not warm or len(cold) != 1:
        raise ValueError("Warm references and one explicit cold context are required.")
    result, position = [], 0
    # The fixed ten-request cycle preserves both marginals and all K/cohort pairs.
    limits = (20, 10, 20, 5, 20, 20, 10, 20, 5, 20)
    for index in range(count):
        is_warm = index % 10 not in (4, 9)
        row = warm[(position + POLICY["seed"]) % len(warm)] if is_warm else cold[0]
        position += is_warm
        result.append(
            (row, limits[(index + (index // 10) * 3) % 10], "warm" if is_warm else "cold")
        )
    return result


def json_http(port, method, path, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=POLICY["timeout_seconds"])
    try:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        connection.request(method, path, encoded, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Response exceeds its bounded size.")
        headers = {name.lower(): value for name, value in response.getheaders()}
        if path == "/metrics":
            value = raw.decode("utf-8")
        else:
            value = json.loads(raw)
        return response.status, value, headers
    finally:
        connection.close()


def validate_response(status, value, headers, row, k, manifest, pin, cached):
    request_id = headers.get("x-request-id")
    if (
        not isinstance(value, dict)
        or not re.fullmatch(r"[0-9a-f]{32}", request_id or "")
        or value.get("request_id") != request_id
        or headers.get("cache-control") != "no-store"
        or headers.get("x-content-type-options") != "nosniff"
    ):
        raise ValueError("Response identity/security envelope differs.")
    if status == 200:
        if (
            value.get("items") != row["trace"]["output"][:k]
            or value.get("route") != row["trace"]["route"]
            or value.get("manifest_sha256") != pin
            or value.get("bundle_version") != manifest["bundle_version"]
            or type(value.get("cutoff")) is not int
            or value["cutoff"] != manifest["snapshot"]["cutoff"]
            or value.get("degraded") is not False
            or value.get("degraded_reason") is not None
            or value.get("cache_status") not in ({"hit", "miss"} if cached else {"disabled"})
        ):
            raise ValueError("Successful workload output differs from its sealed reference.")
        return value["cache_status"]
    expected = {429: "rate_limited", 503: "busy"}
    if status not in expected or value.get("error", {}).get("code") != expected[status]:
        raise ValueError("Unexpected workload status or error envelope.")
    return "rejected"


def metric_snapshot(text):
    rows, seen = [], set()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? ([0-9eE+.\-]+)", line)
        if match is None:
            raise ValueError("Malformed metrics sample.")
        name, raw, value = match.groups()
        pairs = re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"\\]*)"', raw or "")
        if raw and ",".join(f'{key}="{value}"' for key, value in pairs) != raw:
            raise ValueError("Malformed metrics labels.")
        if len(dict(pairs)) != len(pairs):
            raise ValueError("Duplicate metrics labels.")
        labels = dict(pairs)
        key = name, tuple(sorted(pairs))
        numeric = float(value)
        if key in seen or not math.isfinite(numeric) or numeric < 0:
            raise ValueError("Invalid metrics sample identity/value.")
        seen.add(key)
        rows.append((name, labels, numeric))

    def total(name, **wanted):
        return sum(v for n, labels, v in rows if n == name and wanted.items() <= labels.items())

    if total("recsys_memory_sample_success") != 1 or total("recsys_cache_sample_success") != 1:
        raise ValueError("Resource/cache telemetry sampling failed.")
    if total("recsys_ready") != 1 or total("recsys_primary_in_flight") != 0:
        raise ValueError("Metrics require a ready, drained service.")
    return {
        "posts": total("recsys_http_requests_total", endpoint="recommendations", method="POST"),
        "deliveries": total("recsys_deliveries_total"),
        "hits": total("recsys_cache_events_total", event="hits"),
        "misses": total("recsys_cache_events_total", event="misses"),
        "primary": total("recsys_primary_calls_total"),
        "busy": total("recsys_http_errors_total", code="busy"),
        "rate_limited": total("recsys_http_errors_total", code="rate_limited"),
        "observer_errors": total("recsys_observer_errors_total"),
    }


def reconcile(before, after, rows, cached):
    delta = {key: after[key] - before[key] for key in before}
    outcomes = Counter(row["status"] for row in rows)
    hits = sum(row["cache"] == "hit" for row in rows)
    misses = sum(row["cache"] == "miss" for row in rows)
    expected = {
        "posts": len(rows) - outcomes["transport"],
        "deliveries": outcomes[200],
        "hits": hits,
        "misses": misses,
        "primary": misses if cached else outcomes[200],
        "busy": outcomes[503],
        "rate_limited": outcomes[429],
        "observer_errors": 0,
    }
    # A transport failure has unknown server completion, so no complete evidence.
    if outcomes["transport"] or delta != expected:
        raise ValueError("Client outcomes and service telemetry do not reconcile.")
    return delta


def resource_summary(samples):
    if not samples or any(
        type(row["rss_bytes"]) is not int
        or not 0 < row["rss_bytes"] < 2**63
        or type(row["elapsed_seconds"]) not in (int, float)
        or not math.isfinite(row["elapsed_seconds"])
        or row["elapsed_seconds"] < 0
        or type(row.get("cpu_seconds")) not in (int, float)
        or not math.isfinite(row["cpu_seconds"])
        or row["cpu_seconds"] < 0
        for row in samples
    ):
        raise ValueError("Require valid nonempty serving-process memory samples.")
    elapsed = [row["elapsed_seconds"] for row in samples]
    cpu = [row["cpu_seconds"] for row in samples]
    if any(b < a for a, b in zip(cpu, cpu[1:])):
        raise ValueError("Serving CPU counters must not decrease.")
    if any(b <= a for a, b in zip(elapsed, elapsed[1:])):
        raise ValueError("Resource sample timestamps must increase.")
    return {
        "samples": len(samples),
        "sampled_server_cpu_seconds": cpu[-1] - cpu[0],
        "rss_max_bytes": max(row["rss_bytes"] for row in samples),
        "first_sample_seconds": elapsed[0],
        "last_sample_seconds": elapsed[-1],
        "largest_sample_gap_seconds": max((b - a for a, b in zip(elapsed, elapsed[1:])), default=0),
    }


def summarize(rows, *, offered, duration, elapsed, resources):
    if type(offered) is not int or not 0 < offered <= 10000 or len(rows) > offered:
        raise ValueError("Invalid offered/attempted denominator.")
    if not 0 < duration <= elapsed or not math.isfinite(elapsed):
        raise ValueError("Invalid workload observation duration.")
    counts = Counter(str(row["status"]) for row in rows)
    shed = offered - len(rows)
    successes = [row for row in rows if row["status"] == 200]
    warm = [row for row in successes if row["cohort"] == "warm"]
    slices = {}
    for name, selected in (
        ("warm_success", warm),
        ("cold_success", [row for row in successes if row["cohort"] == "cold"]),
        ("warm_uncached", [row for row in warm if row["cache"] in {"disabled", "miss"}]),
        ("warm_cache_hit", [row for row in warm if row["cache"] == "hit"]),
        ("rate_rejected", [row for row in rows if row["status"] == 429]),
        ("busy_rejected", [row for row in rows if row["status"] == 503]),
    ):
        slices[name] = {
            "http": latency_metrics([row["http_seconds"] for row in selected]),
            "schedule_to_end": latency_metrics([row["total_seconds"] for row in selected]),
        }
    dispatch = latency_metrics([row["dispatch_seconds"] for row in rows])
    limits = POLICY["targets"]
    targets = {
        "enough_warm_successes": len(warm) >= limits["minimum_warm_successes"],
        "warm_http_p95": bool(warm)
        and slices["warm_success"]["http"]["latency_p95_ms"] <= limits["warm_p95_ms"],
        "warm_http_p99": bool(warm)
        and slices["warm_success"]["http"]["latency_p99_ms"] <= limits["warm_p99_ms"],
        "rss": resources["rss_max_bytes"] <= limits["rss_bytes"],
        "errors": counts["transport"] / offered <= limits["error_fraction"],
        "rejections": (counts["429"] + counts["503"] + shed) / offered
        <= limits["rejection_fraction"],
        "driver_adequate": bool(rows) and dispatch["latency_p99_ms"] <= limits["dispatch_p99_ms"],
    }
    return {
        "offered": offered,
        "attempted": len(rows),
        "completed_http": len(rows) - counts["transport"],
        "successes": len(successes),
        "client_shed": shed,
        "status_counts": dict(sorted(counts.items())),
        "offered_rps": offered / duration,
        "completed_rps": (len(rows) - counts["transport"]) / elapsed,
        "success_rps": len(successes) / elapsed,
        "duration_seconds": duration,
        "including_drain_seconds": elapsed,
        "rejection_fraction": (counts["429"] + counts["503"] + shed) / offered,
        "transport_error_fraction": counts["transport"] / offered,
        "cache_counts": dict(Counter(row["cache"] for row in successes)),
        "cohort_attempts": dict(Counter(row["cohort"] for row in rows)),
        "k_attempts": dict(Counter(str(row["k"]) for row in rows)),
        "latency": slices,
        "dispatch": dispatch,
        "resources": resources,
        "targets": targets,
        "targets_met": all(targets.values()),
    }


def open_loop(requests, rate, concurrency, invoke, *, process, sample_seconds=0.05):
    """Offer every arrival even when busy; only the declared inflight set can wait."""
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate <= 100:
        raise ValueError("Invalid offered request rate.")
    if type(concurrency) is not int or not 1 <= concurrency <= 32 or not requests:
        raise ValueError("Invalid bounded workload concurrency/requests.")
    started = time.perf_counter()
    samples, rows, futures, errors = [], [], set(), []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            try:
                samples.append(
                    {
                        "elapsed_seconds": time.perf_counter() - started,
                        "rss_bytes": process.memory_info().rss,
                        "cpu_seconds": sum(process.cpu_times()[:2]),
                    }
                )
            except Exception:
                errors.append("resource_sampling_failed")
                return
            stop.wait(sample_seconds)

    def work(index):
        scheduled = started + index / rate
        began = time.perf_counter()
        row = invoke(requests[index])
        ended = time.perf_counter()
        return {
            **row,
            "index": index,
            "http_seconds": ended - began,
            "dispatch_seconds": max(0, began - scheduled),
            "total_seconds": max(0, ended - scheduled),
        }

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for index in range(len(requests)):
                time.sleep(max(0, started + index / rate - time.perf_counter()))
                # Reap completed tasks before offering a new arrival; no queue grows.
                done = {future for future in futures if future.done()}
                rows.extend(future.result() for future in done)
                futures -= done
                if len(futures) < concurrency:
                    futures.add(pool.submit(work, index))
            time.sleep(max(0, started + len(requests) / rate - time.perf_counter()))
            rows.extend(future.result() for future in futures)
    finally:
        stop.set()
        monitor.join(timeout=2)
    if monitor.is_alive() or errors:
        raise ValueError("Serving resource sampling failed.")
    return sorted(rows, key=lambda row: row["index"]), samples, time.perf_counter() - started


def validate_measurement(summary, cell, offered_cohorts, offered_k, delta):
    """Check the same accounting at live collection and checkpoint resumption."""
    validate_mix()

    def number(value, *, positive=False):
        return (
            type(value) in (int, float)
            and math.isfinite(value)
            and (value > 0 if positive else value >= 0)
        )

    duration, elapsed = summary["duration_seconds"], summary["including_drain_seconds"]
    if any(not number(summary[key]) for key in ("transport_error_fraction", "rejection_fraction")):
        raise ValueError("Outcome fractions must be finite nonnegative numbers.")
    if (
        not number(duration, positive=True)
        or duration != POLICY["duration_seconds"]
        or not number(elapsed, positive=True)
        or elapsed < duration
        or any(
            not number(summary[key]) or summary[key] != expected
            for key, expected in (
                ("offered_rps", summary["offered"] / duration),
                ("completed_rps", summary["completed_http"] / elapsed),
                ("success_rps", summary["successes"] / elapsed),
            )
        )
    ):
        raise ValueError("Duration and throughput do not match workload counts.")
    for key, offered in (("cohort_attempts", offered_cohorts), ("k_attempts", offered_k)):
        values = summary[key]
        if (
            not isinstance(values, dict)
            or not set(values) <= set(offered)
            or any(type(v) is not int or not 0 <= v <= offered[k] for k, v in values.items())
            or sum(values.values()) != summary["attempted"]
        ):
            raise ValueError("Attempted traffic does not match the offered mix.")
    counts, caches = summary["status_counts"], summary["cache_counts"]
    allowed = {"hit", "miss"} if cell["cached"] else {"disabled"}
    if (
        not isinstance(caches, dict)
        or not set(caches) <= allowed
        or any(type(v) is not int or v < 0 for v in caches.values())
        or sum(caches.values()) != summary["successes"]
    ):
        raise ValueError("Cache outcomes do not match successful deliveries.")
    expected = {
        "posts": summary["completed_http"],
        "deliveries": summary["successes"],
        "hits": caches.get("hit", 0),
        "misses": caches.get("miss", 0),
        "primary": caches.get("miss", 0) if cell["cached"] else summary["successes"],
        "busy": counts.get("503", 0),
        "rate_limited": counts.get("429", 0),
        "observer_errors": 0,
    }
    if (
        not isinstance(delta, dict)
        or set(delta) != set(expected)
        or any(not number(v) or v != expected[k] for k, v in delta.items())
    ):
        raise ValueError("Stored telemetry does not reconcile with client outcomes.")
    slices = summary["latency"]
    if set(slices) != {
        "warm_success",
        "cold_success",
        "warm_uncached",
        "warm_cache_hit",
        "rate_rejected",
        "busy_rejected",
    }:
        raise ValueError("Missing or foreign latency slices.")
    for name, scopes in slices.items():
        if set(scopes) != {"http", "schedule_to_end"}:
            raise ValueError("Missing latency timing scope.")
        if scopes["http"]["latency_samples"] != scopes["schedule_to_end"]["latency_samples"]:
            raise ValueError("Latency timing scopes have different denominators.")
    n = {key: value["http"]["latency_samples"] for key, value in slices.items()}
    if (
        n["warm_success"] + n["cold_success"] != summary["successes"]
        or n["warm_success"] > summary["cohort_attempts"].get("warm", 0)
        or n["cold_success"] > summary["cohort_attempts"].get("cold", 0)
        or n["warm_uncached"] + n["warm_cache_hit"] != n["warm_success"]
        or n["warm_cache_hit"] > caches.get("hit", 0)
        or n["warm_uncached"] > caches.get("miss", 0) + caches.get("disabled", 0)
        or n["rate_rejected"] != counts.get("429", 0)
        or n["busy_rejected"] != counts.get("503", 0)
    ):
        raise ValueError("Latency slices do not match outcome denominators.")
    resources = summary["resources"]
    for key in (
        "rss_max_bytes",
        "ready_rss_bytes",
        "after_priming_rss_bytes",
        "after_workload_rss_bytes",
        "driver_rss_bytes",
    ):
        if type(resources[key]) is not int or not 0 < resources[key] < 2**63:
            raise ValueError("Resource bytes must be bounded positive integers.")
    for key in (
        "sampled_server_cpu_seconds",
        "server_cpu_seconds",
        "driver_cpu_seconds",
        "first_sample_seconds",
        "last_sample_seconds",
        "largest_sample_gap_seconds",
    ):
        if not number(resources[key]):
            raise ValueError("Resource counters must be finite nonnegative numbers.")
    first, last, gap = (
        resources[key]
        for key in ("first_sample_seconds", "last_sample_seconds", "largest_sample_gap_seconds")
    )
    samples = resources["samples"]
    if (
        type(samples) is not int
        or samples < 2
        or not 0 <= first <= 0.2
        or not duration - 0.2 <= last <= elapsed
        or not 0 < gap <= 0.5
        or last <= first
        or last - first > (samples - 1) * gap + 1e-9
        or resources["sampled_server_cpu_seconds"] > resources["server_cpu_seconds"] + 1e-9
    ):
        raise ValueError("Resource samples do not cover the measured window.")


def run_profile(references, manifest, pin, cell, *, port=8000, process_id=1):
    validate_mix()
    process = psutil.Process(process_id)
    ready_rss = process.memory_info().rss
    ids = set()
    ids_lock = threading.Lock()

    def invoke(request):
        row, k, cohort = request
        try:
            status, value, headers = json_http(
                port, "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
            )
        except (OSError, http.client.HTTPException):
            return {"status": "transport", "cache": "none", "cohort": cohort, "k": k}
        cache = validate_response(status, value, headers, row, k, manifest, pin, cell["cached"])
        with ids_lock:
            if value["request_id"] in ids:
                raise ValueError("Workload request IDs must be fresh.")
            ids.add(value["request_id"])
        return {"status": status, "cache": cache, "cohort": cohort, "k": k}

    def parity():
        for row in references:
            time.sleep(POLICY["reference_spacing_seconds"])
            result = invoke((row, 20, "warm" if row["user_id"] is not None else "cold"))
            if result["status"] != 200:
                raise ValueError("Paced reference pass failed.")

    def metrics():
        status, text, _ = json_http(port, "GET", "/metrics")
        if status != 200:
            raise ValueError("Metrics scrape failed.")
        return metric_snapshot(text)

    parity()
    time.sleep(POLICY["settle_seconds"])
    before = metrics()
    count = POLICY["duration_seconds"] * cell["rate"]
    requests = sequence(references, count)
    primed_rss = process.memory_info().rss
    cpu_before, driver_cpu_before = process.cpu_times(), time.process_time()
    rows, samples, elapsed = open_loop(
        requests,
        cell["rate"],
        cell["concurrency"],
        invoke,
        process=process,
        sample_seconds=POLICY["sample_seconds"],
    )
    after = metrics()
    cpu_after = process.cpu_times()
    resources = resource_summary(samples)
    resources.update(
        {
            "ready_rss_bytes": ready_rss,
            "after_priming_rss_bytes": primed_rss,
            "after_workload_rss_bytes": process.memory_info().rss,
            "server_cpu_seconds": (cpu_after.user + cpu_after.system)
            - (cpu_before.user + cpu_before.system),
            "driver_cpu_seconds": time.process_time() - driver_cpu_before,
            "driver_rss_bytes": psutil.Process().memory_info().rss,
        }
    )
    if (
        resources["last_sample_seconds"] < POLICY["duration_seconds"] - 0.2
        or resources["largest_sample_gap_seconds"] > 0.5
    ):
        raise ValueError("Resource samples do not cover the measured window.")
    delta = reconcile(before, after, rows, cell["cached"])
    result = summarize(
        rows,
        offered=count,
        duration=POLICY["duration_seconds"],
        elapsed=elapsed,
        resources=resources,
    )
    offered_cohorts = dict(Counter(cohort for _, _, cohort in requests))
    offered_k = dict(Counter(str(k) for _, k, _ in requests))
    validate_measurement(result, cell, offered_cohorts, offered_k, delta)
    parity()
    status, ready, _ = json_http(port, "GET", "/health/ready")
    if status != 200 or ready.get("state") != "ready":
        raise ValueError("Workload did not preserve final readiness.")
    return {
        "cell": cell,
        "request_sequence_sha256": hashlib.sha256(
            json.dumps([(r["user_id"], k) for r, k, _ in requests], separators=(",", ":")).encode()
        ).hexdigest(),
        "offered_cohorts": offered_cohorts,
        "offered_k": offered_k,
        "pre_references": len(references),
        "post_references": len(references),
        "parity_passed": True,
        "telemetry_delta": delta,
        "summary": result,
        "cgroup_memory_peak_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text())
        if process_id == 1
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", choices=[row["name"] for row in CELLS], required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256):
        parser.error("Expected an immutable manifest pin.")
    manifest_path = Path("/model/model_manifest.json")
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != args.manifest_sha256:
        raise ValueError("Workload manifest pin differs.")
    manifest = json.loads(manifest_path.read_text())
    references_path = Path("/model/references.json")
    if (
        hashlib.sha256(references_path.read_bytes()).hexdigest()
        != manifest["components"]["references.json"]["sha256"]
    ):
        raise ValueError("Workload references differ from sealed inventory.")
    references = json.loads(references_path.read_text())
    if len(references) != 101 or sum(row["user_id"] is not None for row in references) != 100:
        raise ValueError("Require all 100 warm/one cold sealed references.")
    cell = next(row for row in CELLS if row["name"] == args.cell)
    print(
        json.dumps(run_profile(references, manifest, args.manifest_sha256, cell), allow_nan=False)
    )


if __name__ == "__main__":
    main()
