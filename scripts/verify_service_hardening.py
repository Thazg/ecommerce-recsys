"""Verify local HTTP protection and paced reference parity on the sealed bundle."""

from __future__ import annotations

import argparse
import http.client
import importlib.metadata
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import digest, file_sha, runtime_code, verify_inventory
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.serving.security import SecuritySettings

if __package__:
    from scripts.verify_recommendation_api import (
        ROOT,
        implementation_identity,
        publish_receipt,
        reference_inputs,
        verify_openapi,
    )
    from scripts.verify_service_cache import benefit_gates, check_response
    from scripts.verify_service_observability import parse_metrics, value
else:
    from verify_recommendation_api import (
        ROOT,
        implementation_identity,
        publish_receipt,
        reference_inputs,
        verify_openapi,
    )
    from verify_service_cache import benefit_gates, check_response
    from verify_service_observability import parse_metrics, value

INTERVAL = 0.26  # <4 attempts/s; outside measured client round-trip latency.


def code_identity():
    return {
        **implementation_identity(),
        **{
            name: file_sha(ROOT / name)
            for name in (
                "scripts/verify_service_hardening.py",
                "scripts/verify_service_cache.py",
                "scripts/verify_service_observability.py",
            )
        },
    }


class HardeningProbe:
    def __init__(self, port, *, token=None):
        self.port, self.token = port, token
        self.last_attempt = 0.0
        self.ids = set()
        self.http_calls = self.deliveries = 0

    def call(
        self, method, path, body=None, *, expected=200, headers=None, paced=True, credential=True
    ):
        if method == "POST" and path.rstrip("/") == "/v1/recommendations" and paced:
            time.sleep(max(0, INTERVAL - (time.monotonic() - self.last_attempt)))
            self.last_attempt = time.monotonic()
        fields = {"Content-Type": "application/json"}
        if self.token is not None and credential:
            fields["Authorization"] = "Bearer " + self.token
        fields.update(headers or {})
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            started = time.perf_counter()
            connection.request(method, path, body, headers=fields)
            response = connection.getresponse()
            raw = response.read(1048576)
            elapsed = time.perf_counter() - started
            if response.status != expected:
                raise ValueError("Unexpected HTTP status in hardening probe.")
            if (
                response.getheader("Cache-Control") != "no-store"
                or response.getheader("X-Content-Type-Options") != "nosniff"
            ):
                raise ValueError("Response security headers are missing.")
            request_id = response.getheader("X-Request-ID")
            if not re.fullmatch("[0-9a-f]{32}", request_id or "") or request_id in self.ids:
                raise ValueError("Server correlation identity is invalid or reused.")
            self.ids.add(request_id)
            if path == "/metrics" and expected == 200:
                result = raw.decode("utf-8")
            else:
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError("Hardening probe expected valid JSON.") from None
                if not isinstance(result, dict) or (
                    path != "/openapi.json" and result.get("request_id") != request_id
                ):
                    raise ValueError("Response envelope differs from the HTTP identity.")
            if path != "/metrics":
                self.http_calls += 1
            if method == "POST" and path == "/v1/recommendations" and expected == 200:
                self.deliveries += 1
            if expected == 429 and not (response.getheader("Retry-After") or "").isdigit():
                raise ValueError("Rate denial has no integer retry guidance.")
            return result, elapsed
        finally:
            connection.close()


def raw_probe(port, data, *, expected=None, incomplete=False):
    with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
        sock.sendall(data)
        if incomplete:
            if sock.recv(1) != b"":
                raise ValueError("Incomplete headers were not closed.")
            return None
        response = http.client.HTTPResponse(sock)
        response.begin()
        raw = response.read(65536)
        if response.status != expected:
            raise ValueError("Raw HTTP protection returned an unexpected status.")
        if expected == 408:
            result = json.loads(raw)
            if (
                result.get("error", {}).get("code") != "body_timeout"
                or response.getheader("Connection") != "close"
            ):
                raise ValueError("Body timeout contract differs.")
        return response.status


def trailer_probes(port, host, auth):
    prefix = b"POST /v1/recommendations HTTP/1.1\r\n" + host + auth
    raw_probe(
        port, prefix + b"Transfer-Encoding: chunked\r\nTrailer: X-Extra\r\n\r\n", expected=400
    )
    with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
        # Waiting for 100 Continue proves that ASGI has admitted a body reader.
        # Nonempty trailers must still prevent body completion/model admission.
        sock.sendall(
            prefix
            + b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\nExpect: 100-continue\r\n\r\n"
        )
        interim = b""
        while b"\r\n\r\n" not in interim:
            chunk = sock.recv(65536)
            if not chunk or len(interim) + len(chunk) > 4096:
                raise ValueError("Body-reader handshake did not complete.")
            interim += chunk
        if interim != b"HTTP/1.1 100 Continue\r\n\r\n":
            raise ValueError("Unexpected body-reader handshake.")
        sock.sendall(b"2\r\n{}\r\n0\r\nX-Extra: " + b"a" * 17000 + b"\r\n\r\n")
        response = http.client.HTTPResponse(sock)
        response.begin()
        response.read(65536)
        if response.status != 400 or response.getheader("Connection") != "close":
            raise ValueError("Undeclared trailers were not rejected.")


def security_checks(probe):
    port = probe.port
    if probe.token is not None:
        probe.call("GET", "/health/ready", expected=401, credential=False)
        probe.call("GET", "/metrics", expected=401, credential=False)
        probe.call("GET", "/health/live", credential=False)
    probe.call("POST", "/v1/recommendations", {}, headers={"Host": "foreign.invalid"}, expected=400)
    probe.call("POST", "/v1/recommendations", {}, headers={"Origin": "null"}, expected=403)
    probe.call(
        "POST", "/v1/recommendations", {}, headers={"Content-Encoding": "gzip"}, expected=415
    )
    probe.call("POST", "/v1/recommendations", b"x" * 8193, expected=413)
    probe.call("POST", "/v1/recommendations", b'{"k":1,"k":2}', expected=400)
    host = f"Host: 127.0.0.1:{port}\r\n".encode()
    auth = ("Authorization: Bearer " + probe.token + "\r\n").encode() if probe.token else b""
    raw_probe(
        port,
        b"GET /health/live HTTP/1.1\r\n" + host + b"X: " + b"x" * 17000 + b"\r\n\r\n",
        expected=400,
    )
    raw_probe(port, b"GET /health/live HTTP/1.1\r\nHost:", incomplete=True)
    raw_probe(
        port,
        b"POST /v1/recommendations HTTP/1.1\r\n"
        + host
        + auth
        + b"Content-Type: application/json\r\nContent-Length: 20\r\n\r\n{",
        expected=408,
    )
    probe.http_calls += 1  # Raw ASGI timeout; the other two never reach ASGI.
    trailer_probes(port, host, auth)
    probe.http_calls += 1  # Undeclared trailers disconnect an already-started ASGI reader.
    # Intentionally finite invalid-input bursts exercise rate denial without
    # fitting models or inflating successful delivery counts.
    statuses = []
    for _ in range(15):
        # Get status directly, then validate the normal fixed error contract.
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            headers = {"Content-Type": "application/json", "X-Forwarded-For": secrets.token_hex(8)}
            if probe.token:
                headers["Authorization"] = "Bearer " + probe.token
            connection.request("POST", "/v1/recommendations", b"{", headers)
            response = connection.getresponse()
            result = json.loads(response.read())
            if response.status not in (400, 429) or result.get("error", {}).get("code") != (
                "rate_limited" if response.status == 429 else "invalid_json"
            ):
                raise ValueError("Burst did not produce bounded validation/rate errors.")
            if response.status == 429 and not (response.getheader("Retry-After") or "").isdigit():
                raise ValueError("Missing rate Retry-After.")
            statuses.append(response.status)
            probe.http_calls += 1
        finally:
            connection.close()
    if 429 not in statuses:
        raise ValueError("Finite burst failed to reach the request budget.")
    time.sleep(2.1)  # Refill default per-peer burst before a healthy parity call.
    return {
        "host_origin_encoding_body_json": True,
        "header_size": True,
        "header_deadline": True,
        "body_deadline": True,
        "request_trailers_rejected": True,
        "forwarded_burst_denials": statuses.count(429),
        "auth_operational_endpoints": probe.token is not None,
        "scope": "Default 5s deadlines and finite burst; overflow/cancellation/concurrency edges use tests.",
    }


def run_phase(bundle, pin, manifest, references, *, enabled):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token = secrets.token_urlsafe(32) if enabled else None
    environment = os.environ.copy()
    environment.pop("RECSYS_API_TOKEN", None)
    environment.pop("RECSYS_API_TOKEN_FILE", None)
    if token is not None:
        environment["RECSYS_API_TOKEN"] = token
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
        command += ["--cache-max-entries", "256", "--busy-policy", "recent_popularity"]
    log_path = ROOT / ".local" / ("hardening_on.log" if enabled else "hardening_off.log")
    log_path.parent.mkdir(exist_ok=True)
    rss, stop = [], threading.Event()
    probe = HardeningProbe(port, token=token)
    started = time.perf_counter()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
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
        try:
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Hardening server exited before readiness; inspect private logs."
                    )
                if time.perf_counter() - started > 180:
                    raise TimeoutError("Hardening startup deadline exceeded.")
                try:
                    ready, _ = probe.call("GET", "/health/ready")
                    break
                except OSError:
                    time.sleep(0.2)
            startup_seconds = time.perf_counter() - started
            ready_rss = child.memory_info().rss
            schema, _ = probe.call("GET", "/openapi.json")
            verify_openapi(schema)
            if any(
                "415" not in schema["paths"][path]["get"]["responses"]
                for path in ("/health/live", "/health/ready")
            ):
                raise ValueError("OpenAPI omits a shared content-encoding error.")
            if (
                schema["info"]["version"] != "1.2.0"
                or ready["primary_calls"] != 0
                or ready["cache"]["enabled"] != enabled
            ):
                raise ValueError("Unexpected hardening API/cache contract.")
            timings, outputs, ids = {}, [], []
            warm = [r for r in references if r["trace"]["route"] == "hybrid_learned"]
            cold = next(r for r in references if r["trace"]["route"] == "recent_popularity")
            if not enabled:
                probe.call("POST", "/v1/recommendations", {"user_id": warm[0]["user_id"]})
            for path in ("miss", "hit") if enabled else ("disabled",):
                measured = {"warm": [], "cold": []}
                for row in references:
                    result, elapsed = probe.call(
                        "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": 20}
                    )
                    output = check_response(result, row, manifest, pin, 20, path)
                    ids.append(result["request_id"])
                    if path != "hit":
                        outputs.append(output)
                    measured[
                        "warm" if row["trace"]["route"] == "hybrid_learned" else "cold"
                    ].append(elapsed)
                for cohort, values in measured.items():
                    timings[f"{path}_{cohort}" if enabled else cohort] = latency_metrics(values)
            for row in warm[:3]:
                for k in (5, 10):
                    result, _ = probe.call(
                        "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
                    )
                    check_response(result, row, manifest, pin, k, "hit" if enabled else "disabled")
            for user in (None, "hardening-probe-unknown-user"):
                result, _ = probe.call("POST", "/v1/recommendations", {"user_id": user})
                check_response(result, cold, manifest, pin, 20, "hit" if enabled else "disabled")
            checks = security_checks(probe)
            result, _ = probe.call("POST", "/v1/recommendations", {"user_id": warm[0]["user_id"]})
            check_response(result, warm[0], manifest, pin, 20, "hit" if enabled else "disabled")
            final, _ = probe.call("GET", "/health/ready")
            metrics_text, _ = probe.call("GET", "/metrics")
            metrics = parse_metrics(metrics_text)
            expected_primary = (
                101 if enabled else 111
            )  # Warm-up +101 +6 prefixes +2 cold +recovery.
            if (
                final["state"] != "ready"
                or final["primary_calls"] != expected_primary
                or value(metrics, "recsys_http_requests_total") != probe.http_calls
                or value(metrics, "recsys_deliveries_total") != probe.deliveries
                or value(metrics, "recsys_primary_in_flight") != 0
                or value(metrics, "recsys_observer_errors_total") != 0
                or value(metrics, "recsys_transport_events_total", event="header_timeout") != 1
                or value(metrics, "recsys_transport_events_total", event="input_limit") != 1
                or value(metrics, "recsys_transport_events_total", event="trailers_rejected") != 2
                or value(metrics, "recsys_http_errors_total", code="body_timeout") != 1
            ):
                raise ValueError("Protection/HTTP/model telemetry does not reconcile.")
            if enabled and (final["cache"]["misses"] != 101 or final["cache"]["hits"] != 110):
                raise ValueError("Paced cache reference counters do not reconcile.")
            after_rss = child.memory_info().rss
            # The preceding scrape is serialized after the completed health log.
            records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.startswith('{"event":')
            ]
            serialized = json.dumps(records)
            if sum(row["event"] == "http_request" for row in records) != probe.http_calls:
                raise ValueError("Owned HTTP logs do not reconcile with counters.")
            if (token and token in log_path.read_text(encoding="utf-8")) or any(
                s in serialized
                for s in (
                    "user_id",
                    "hardening-probe-unknown-user",
                    '"items"',
                    "traceback",
                    "foreign.invalid",
                    "127.0.0.1",
                )
            ):
                raise ValueError("Probe found sensitive input in owned logs.")
        finally:
            stop.set()
            sampler.join(5)
            process.terminate()
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(10)
    policy = SecuritySettings(
        authorities=(f"127.0.0.1:{port}", f"localhost:{port}"),
        token=token.encode() if token else None,
    )
    return {
        "cache_enabled": enabled,
        "policy": policy.public_policy(),
        "startup_seconds": startup_seconds,
        "timing": timings,
        "reference_outputs_sha256": digest(outputs),
        "protection_checks": checks,
        "final": final,
        "memory": {
            "ready_rss_bytes": ready_rss,
            "after_requests_rss_bytes": after_rss,
            "sampled_peak_rss_bytes": max([ready_rss, after_rss, *rss]),
            "sampling_interval_seconds": 0.05,
            "charter_target_bytes": 2 * 1024**3,
            "observed_samples_within_target": max([ready_rss, after_rss, *rss]) <= 2 * 1024**3,
        },
        "telemetry": {
            "http_requests": probe.http_calls,
            "deliveries": probe.deliveries,
            "owned_json_records": len(records),
            "owned_events_sha256": digest(records),
            "sample_series": len(metrics),
            "metrics_text": metrics_text,
            "all_passed": True,
        },
    }


def verify(bundle, pin):
    manifest, references, reference_sha = reference_inputs(bundle, pin)
    if (
        sum(r["trace"]["route"] == "hybrid_learned" for r in references) != 100
        or sum(r["trace"]["route"] == "recent_popularity" for r in references) != 1
    ):
        raise ValueError("This receipt requires the sealed 100-warm/one-cold sample.")
    verify_inventory(bundle, pin)
    source = code_identity()
    off = run_phase(bundle, pin, manifest, references, enabled=False)
    on = run_phase(bundle, pin, manifest, references, enabled=True)
    if (
        code_identity() != source
        or off["reference_outputs_sha256"] != on["reference_outputs_sha256"]
    ):
        raise ValueError("Source changed during verification or reference outputs differ.")
    gates = benefit_gates(off["timing"], on["timing"])
    return {
        "schema_version": 1,
        "api_version": "1.2.0",
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
                n: importlib.metadata.version(n)
                for n in ("fastapi", "starlette", "uvicorn", "h11", "pydantic", "anyio", "psutil")
            },
        },
        "reference_pacing_seconds": INTERVAL,
        "cache_off_anonymous": off,
        "cache_on_bearer": on,
        "parity": {
            "warm_references": len(references) - 1,
            "cold_references": 1,
            "prefix_checks_per_phase": 6,
            "cold_reuse_checks_per_phase": 2,
            "post_denial_recovery_per_phase": 1,
            "all_passed": True,
        },
        "benefit_gates": {**gates, "all_passed": all(gates.values())},
        "limits": [
            "Loopback Windows finite sample; not public security certification, Linux full-bundle parity or load/SLA evidence.",
            "Authentication and cache differ between processes; their cost is not isolated. Per-call pacing is excluded from latency.",
            "Cold has one reference; 50ms RSS samples lower-bound peak. Existing 2GiB/500ms targets are not waived.",
            "Protocol rejections can precede ASGI or disconnect an active body reader. Transport counters do not imply JSON/request IDs or completed deliveries.",
            "Read/socket overflow, cancellation, pipelining and stale timers use deterministic and real-socket tests.",
            "Probe children terminate after checks; graceful drain is covered separately. Tokens are ephemeral and never persisted.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve completed receipts; select a new output path.")
    try:
        receipt = verify(args.bundle, args.manifest_sha256)
        publish_receipt(args.output, receipt)
    except (OSError, RuntimeError, ValueError, TimeoutError):
        parser.exit(1, "Hardening verification failed; inspect private probe logs.\n")
    print(
        json.dumps(
            {
                "parity": receipt["parity"],
                "benefit_gates": receipt["benefit_gates"],
                "receipt": args.output.as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
