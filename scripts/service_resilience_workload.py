"""Fixed snapshot load and lifecycle probes inside an isolated Linux container."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import signal
import socket
import struct
import time
import types
from collections import Counter
from pathlib import Path
from threading import Lock

import psutil

if "_CAPACITY_SOURCE" not in globals():
    _CAPACITY_SOURCE = (Path(__file__).with_name("http_capacity_workload.py")).read_text(
        encoding="utf-8"
    )

POLICY = {
    "version": "snapshot-service-resilience-v1",
    "warm_fraction": 0.8,
    "k_mix": {"20": 0.6, "10": 0.2, "5": 0.2},
    "seed": 42,
    "reference_spacing_seconds": 0.26,
    "settle_seconds": 3,
    "recovery_seconds": 10,
    "observation_seconds": 5,
    "signal_lag_seconds": 0.05,
    "pressure_bytes": 512 * 1024**2,
    "startup_seconds": 150,
    "invalid_startup_seconds": 90,
    "stop_seconds": 30,
    "cache": "off",
    "busy_policy": "reject",
    "targets": {
        "warm_p95_ms": 300,
        "warm_p99_ms": 500,
        "rss_bytes": 2 * 1024**3,
        "error_fraction": 0.01,
        "rejection_fraction": 0.01,
        "dispatch_p99_ms": 10,
        "minimum_warm_successes": 100,
    },
    "scope": "Docker Desktop Linux; network none; client and server share 2CPU/4GiB",
}
CELLS = (
    {
        "name": "sustained",
        "pressure_bytes": 0,
        "phases": [{"name": "steady", "seconds": 600, "rate": 1, "concurrency": 4}],
    },
    {
        "name": "burst-recovery",
        "pressure_bytes": 0,
        "phases": [
            phase
            for cycle in range(1, 4)
            for phase in (
                {"name": f"burst-{cycle}", "seconds": 10, "rate": 8, "concurrency": 16},
                {"name": f"quiet-{cycle}", "seconds": 20, "rate": 1, "concurrency": 4},
            )
        ],
    },
    {
        "name": "memory-pressure",
        "pressure_bytes": POLICY["pressure_bytes"],
        "phases": [{"name": "occupied", "seconds": 180, "rate": 1, "concurrency": 4}],
    },
)


def capacity_helper(seconds=150):
    """Give this experiment a private helper namespace and declared duration.

    M23 source and global state remain unchanged. This is a new experiment with
    different windows; it never migrates or resumes an M23 checkpoint.
    """
    module = types.ModuleType("_resilience_capacity_helper")
    exec(compile(_CAPACITY_SOURCE, "http_capacity_workload.py", "exec"), module.__dict__)
    module.POLICY = {**module.POLICY, "duration_seconds": seconds}
    if POLICY["warm_fraction"] != 0.8 or POLICY["k_mix"] != module.POLICY["k_mix"]:
        raise ValueError("Unsupported resilience traffic mix.")
    if POLICY["seed"] != module.POLICY["seed"]:
        raise ValueError("Resilience schedule seed differs from its declared helper.")
    if POLICY["targets"] != module.POLICY["targets"]:
        raise ValueError("Resilience targets differ from the declared charter thresholds.")
    module.validate_mix()
    return module


def sequence_identity(requests):
    return hashlib.sha256(
        json.dumps([(row["user_id"], k) for row, k, _ in requests], separators=(",", ":")).encode()
    ).hexdigest()


def validate_window(result, phase, references):
    helper = capacity_helper(phase["seconds"])
    requests = helper.sequence(references, phase["seconds"] * phase["rate"])
    cohorts = dict(Counter(c for _, _, c in requests))
    limits = dict(Counter(str(k) for _, k, _ in requests))
    summary = result["summary"]
    if (
        result.get("phase") != phase
        or result.get("request_sequence_sha256") != sequence_identity(requests)
        or result.get("offered_cohorts") != cohorts
        or result.get("offered_k") != limits
        or type(summary.get("offered")) is not int
        or summary["offered"] != len(requests)
        or type(summary.get("attempted")) is not int
        or not 0 <= summary["attempted"] <= len(requests)
        or summary.get("client_shed") != len(requests) - summary["attempted"]
        or summary.get("completed_http") != summary["attempted"]
        or sum(summary.get("status_counts", {}).values()) != summary["attempted"]
        or summary.get("successes") != summary.get("status_counts", {}).get("200", 0)
    ):
        raise ValueError("Window schedule or outcome accounting differs.")
    helper.validate_measurement(
        summary, {"cached": False}, cohorts, limits, result.get("telemetry_delta")
    )
    # The generic upstream summary classifier uses the unchanged charter targets.
    counts = summary["status_counts"]
    if any(
        type(summary[k]) is not int or summary[k] < 0
        for k in ("offered", "attempted", "completed_http", "successes", "client_shed")
    ):
        raise ValueError("Window counters must be nonnegative integers.")
    if not set(counts) <= {"200", "429", "503"} or any(
        type(v) is not int or v < 0 for v in counts.values()
    ):
        raise ValueError("Invalid window outcome counters.")
    for timing in [
        summary["dispatch"],
        *(scope for row in summary["latency"].values() for scope in row.values()),
    ]:
        import math

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
            or timing["latency_samples"] < 0
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0
                for k, v in timing.items()
                if k != "latency_samples"
            )
            or not timing["latency_p50_ms"] <= timing["latency_p95_ms"] <= timing["latency_p99_ms"]
        ):
            raise ValueError("Invalid window latency evidence.")
    if summary["dispatch"]["latency_samples"] != summary["attempted"]:
        raise ValueError("Dispatch denominator differs.")
    rejection = (counts.get("429", 0) + counts.get("503", 0) + summary["client_shed"]) / len(
        requests
    )
    warm = summary["latency"]["warm_success"]["http"]
    targets = helper.POLICY["targets"]
    expected = {
        "enough_warm_successes": warm["latency_samples"] >= targets["minimum_warm_successes"],
        "warm_http_p95": bool(warm["latency_samples"])
        and warm["latency_p95_ms"] <= targets["warm_p95_ms"],
        "warm_http_p99": bool(warm["latency_samples"])
        and warm["latency_p99_ms"] <= targets["warm_p99_ms"],
        "rss": summary["resources"]["rss_max_bytes"] <= targets["rss_bytes"],
        "errors": summary["transport_error_fraction"] <= targets["error_fraction"],
        "rejections": rejection <= targets["rejection_fraction"],
        "driver_adequate": bool(summary["attempted"])
        and summary["dispatch"]["latency_p99_ms"] <= targets["dispatch_p99_ms"],
    }
    if (
        summary["transport_error_fraction"] != 0
        or summary["rejection_fraction"] != rejection
        or summary["targets"] != expected
        or any(type(v) is not bool for v in summary["targets"].values())
        or type(summary["targets_met"]) is not bool
        or summary["targets_met"] != all(expected.values())
    ):
        raise ValueError("Window target classification differs from measurements.")
    return result


class Client:
    def __init__(self, references, manifest, pin, port):
        self.references, self.manifest, self.pin, self.port = references, manifest, pin, port
        self.helper = capacity_helper()
        self.ids, self.lock = set(), Lock()

    def invoke(self, request):
        row, k, cohort = request
        try:
            status, value, headers = self.helper.json_http(
                self.port, "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
            )
        except (OSError, http.client.HTTPException):
            return {"status": "transport", "cache": "none", "cohort": cohort, "k": k}
        cache = self.helper.validate_response(
            status, value, headers, row, k, self.manifest, self.pin, False
        )
        with self.lock:
            if value["request_id"] in self.ids:
                raise ValueError("Repeated workload request identity.")
            self.ids.add(value["request_id"])
        return {"status": status, "cache": cache, "cohort": cohort, "k": k}

    def parity(self):
        for row in self.references:
            time.sleep(POLICY["reference_spacing_seconds"])
            if self.invoke((row, 20, "warm" if row["user_id"] else "cold"))["status"] != 200:
                raise ValueError("Paced sealed reference failed.")
        return len(self.references)

    def metrics(self):
        status, text, _ = self.helper.json_http(self.port, "GET", "/metrics")
        if status != 200:
            raise ValueError("Metrics unavailable.")
        return self.helper.metric_snapshot(text)

    def recover_pair(self):
        start = time.perf_counter()
        for row in (self.references[0], self.references[-1]):
            time.sleep(POLICY["reference_spacing_seconds"])
            if self.invoke((row, 20, "warm" if row["user_id"] else "cold"))["status"] != 200:
                raise ValueError("Post-burst recovery reference failed.")
        elapsed = time.perf_counter() - start
        if elapsed > POLICY["recovery_seconds"]:
            raise ValueError("Post-burst recovery exceeded its deadline.")
        self.metrics()
        return {"references": 2, "seconds": elapsed, "ready_and_drained": True}


def run_load(references, manifest, pin, cell, *, port=8000, process_id=1):
    client = Client(references, manifest, pin, port)
    process = psutil.Process(process_id)
    ready_rss = process.memory_info().rss
    pre = client.parity()
    own = psutil.Process()
    rss_before = own.memory_info().rss
    memory = None
    phases = []
    try:
        amount = cell["pressure_bytes"]
        if amount:
            memory = bytearray(amount)
            for index in range(0, amount, 4096):
                memory[index] = 1
        rss_after = own.memory_info().rss
        if amount and rss_after - rss_before < amount * 0.9:
            raise ValueError("Requested memory occupancy was not observed.")
        time.sleep(POLICY["settle_seconds"])
        for phase in cell["phases"]:
            helper = capacity_helper(phase["seconds"])
            requests = helper.sequence(references, phase["seconds"] * phase["rate"])
            before = client.metrics()
            primed = process.memory_info().rss
            cpu_before, driver_before = process.cpu_times(), time.process_time()
            rows, samples, elapsed = helper.open_loop(
                requests,
                phase["rate"],
                phase["concurrency"],
                client.invoke,
                process=process,
                sample_seconds=helper.POLICY["sample_seconds"],
            )
            after = client.metrics()
            cpu_after = process.cpu_times()
            resources = helper.resource_summary(samples)
            resources.update(
                {
                    "ready_rss_bytes": ready_rss,
                    "after_priming_rss_bytes": primed,
                    "after_workload_rss_bytes": process.memory_info().rss,
                    "server_cpu_seconds": cpu_after.user
                    + cpu_after.system
                    - cpu_before.user
                    - cpu_before.system,
                    "driver_cpu_seconds": time.process_time() - driver_before,
                    "driver_rss_bytes": own.memory_info().rss,
                }
            )
            result = {
                "phase": phase,
                "request_sequence_sha256": sequence_identity(requests),
                "offered_cohorts": dict(Counter(c for _, _, c in requests)),
                "offered_k": dict(Counter(str(k) for _, k, _ in requests)),
                "telemetry_delta": helper.reconcile(before, after, rows, False),
                "summary": helper.summarize(
                    rows,
                    offered=len(requests),
                    duration=phase["seconds"],
                    elapsed=elapsed,
                    resources=resources,
                ),
            }
            validate_window(result, phase, references)
            if phase["name"].startswith("quiet-"):
                result["recovery"] = client.recover_pair()
            phases.append(result)
    finally:
        memory = None
    post = client.parity()
    client.metrics()
    return {
        "cell": cell,
        "phases": phases,
        "pre_references": pre,
        "post_references": post,
        "parity_passed": True,
        "pressure": {
            "allocated_bytes": cell["pressure_bytes"],
            "driver_rss_before_bytes": rss_before,
            "driver_rss_occupied_bytes": rss_after,
        },
        "cgroup_memory_peak_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text())
        if process_id == 1
        else None,
    }


def observe_request(client):
    """Return a socket only after observing an actual numerical worker."""
    for row in client.references[:5]:
        time.sleep(POLICY["reference_spacing_seconds"])
        sock = socket.create_connection(("127.0.0.1", client.port), timeout=10)
        body = json.dumps({"user_id": row["user_id"], "k": 20}).encode()
        sock.sendall(
            f"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:{client.port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        deadline = time.monotonic() + POLICY["observation_seconds"]
        while time.monotonic() < deadline:
            status, text, _ = client.helper.json_http(client.port, "GET", "/metrics")
            if status != 200:
                sock.close()
                raise ValueError("Lifecycle observation metrics failed.")
            if "recsys_primary_in_flight 1\n" in text:
                return sock, row, time.perf_counter()
            if "recsys_primary_in_flight 0\n" not in text:
                sock.close()
                raise ValueError("Lifecycle worker gauge is missing.")
            time.sleep(0.005)
        sock.close()
    raise ValueError("No in-flight primary was witnessed; lifecycle probe is incomplete.")


def run_lifecycle(references, manifest, pin, kind, *, port=8000, process_id=1):
    if kind not in {"client-disconnect", "inflight-drain"}:
        raise ValueError("Unknown lifecycle probe.")
    client = Client(references, manifest, pin, port)
    pre = client.parity()
    before = client.metrics()
    sock, row, observed = observe_request(client)
    try:
        if kind == "inflight-drain":
            os.kill(process_id, signal.SIGTERM)
            lag = time.perf_counter() - observed
            if lag > POLICY["signal_lag_seconds"]:
                raise ValueError("Primary observation is too stale for the drain signal.")
            response = http.client.HTTPResponse(sock)
            response.begin()
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Drain response exceeds its bound.")
            value = json.loads(raw)
            headers = {k.lower(): v for k, v in response.getheaders()}
            client.helper.validate_response(
                response.status, value, headers, row, 20, manifest, pin, False
            )
            if response.status != 200 or value["request_id"] in client.ids:
                raise ValueError(
                    "Accepted drain request did not finish with a fresh sealed success."
                )
            return {
                "kind": kind,
                "pre_references": pre,
                "primary_witnessed": True,
                "signal": "SIGTERM",
                "observation_to_signal_seconds": lag,
                "accepted_response_parity": True,
            }
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    finally:
        sock.close()
    start = time.perf_counter()
    while True:
        try:
            after = client.metrics()
            break
        except ValueError:
            if time.perf_counter() - start > POLICY["recovery_seconds"]:
                raise ValueError("Disconnected primary did not drain.") from None
            time.sleep(0.01)
    if (
        after["primary"] <= before["primary"]
        or after["observer_errors"] != before["observer_errors"]
    ):
        raise ValueError("Disconnect worker accounting differs.")
    drain_seconds = time.perf_counter() - start
    post = client.parity()
    client.metrics()
    return {
        "kind": kind,
        "pre_references": pre,
        "post_references": post,
        "primary_witnessed": True,
        "ready_and_drained": True,
        "drain_seconds": drain_seconds,
        "parity_passed": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=[c["name"] for c in CELLS] + ["client-disconnect", "inflight-drain"],
        required=True,
    )
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    manifest_path = Path("/model/model_manifest.json")
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != args.manifest_sha256:
        raise ValueError("Resilience model manifest differs.")
    manifest = json.loads(manifest_path.read_text())
    path = Path("/model/references.json")
    if (
        hashlib.sha256(path.read_bytes()).hexdigest()
        != manifest["components"]["references.json"]["sha256"]
    ):
        raise ValueError("Resilience sealed references differ.")
    references = json.loads(path.read_text())
    if len(references) != 101 or sum(r["user_id"] is not None for r in references) != 100:
        raise ValueError("Require all sealed100warm/onecold references.")
    cell = next((c for c in CELLS if c["name"] == args.profile), None)
    result = (
        run_load(references, manifest, args.manifest_sha256, cell)
        if cell
        else run_lifecycle(references, manifest, args.manifest_sha256, args.profile)
    )
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
