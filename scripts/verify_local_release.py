"""Qualify the indexed snapshot API on an owned loopback process, without fitting."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import importlib.metadata
import json
import math
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import digest, environment, verify_inventory
from ecommerce_recsys.evaluation.latency import latency_metrics
from scripts.profile_snapshot_memory import publish, sources, validate_output_path
from scripts.verify_recommendation_api import reference_inputs
from scripts.verify_service_cache import check_response
from scripts.verify_service_observability import parse_metrics, value

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION = "local-snapshot-release-boundary-v1"
POLICY = {
    "host": "127.0.0.1",
    "reader": "indexed",
    "cache": "disabled",
    "busy_policy": "reject",
    "numeric_threads": 1,
    "reference_counts": {"warm": 100, "cold": 1},
    "prefix_calls": 6,
    "denial_calls": 8,
    "steady": {"arrivals": 120, "rate": 1, "warm": 100, "cold": 20},
    "burst": {"arrivals": 32, "rate": 16, "warm": 32, "cold": 0},
    "client_workers": 4,
    "request_timeout_seconds": 10,
    "startup_deadline_seconds": 120,
    "overall_deadline_seconds": 600,
    "stop_deadline_seconds": 20,
    "recovery_refill_seconds": 2,
    "recovery_deadline_seconds": 10,
    "sample_interval_seconds": 0.05,
    "maximum_sample_gap_seconds": 0.2,
    "maximum_dispatch_lateness_seconds": 0.25,
    "loaded_rss_target_bytes": 2 * 1024**3,
    "warm_p95_target_ms": 300,
    "warm_p99_target_ms": 500,
    "http_deadline": "absolute connect/header/body wall deadline with owned socket abort",
    "control_startup": "pre-startup EOF must exit without publishing readiness",
    "resource_consistency": "phase peaks/durations must fit the containing process and assessment",
    "scope": "Windows/local loopback constructed reference workload; no public API or SLO",
}


def identity():
    paths = [
        "scripts/serve_local_snapshot.py",
        "scripts/verify_local_release.py",
        "scripts/verify_recommendation_api.py",
        "scripts/verify_service_cache.py",
        "scripts/verify_service_observability.py",
        "tests/unit/test_local_demonstration.py",
        "tests/unit/test_local_release.py",
        "tests/integration/test_local_snapshot_release.py",
        "requirements/serving.txt",
        "requirements/serving-test.txt",
    ]
    import hashlib

    return {
        **sources(),
        **{
            name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in paths
        },
    }


def runtime():
    return {
        **environment(),
        **{
            name: importlib.metadata.version(name)
            for name in ("psutil", "fastapi", "uvicorn", "h11")
        },
    }


def finite(number, *, positive=False):
    if type(number) not in (int, float) or not -1e12 <= number <= 1e12 or not math.isfinite(number):
        raise ValueError("Measurement must be finite numeric data.")
    if number < 0 or (positive and number == 0):
        raise ValueError("Measurement has an invalid bound.")
    return number


class Probe:
    def __init__(self, port, token, deadline):
        self.port, self.token, self.deadline = port, token, deadline
        self.ids, self.statuses, self.outputs = set(), Counter(), []
        self.lock = threading.Lock()
        self.active_sockets = set()
        self.aborted = False

    @staticmethod
    def interrupt(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def abort(self):
        """Interrupt owned I/O before executor cleanup; never wait on a socket read."""
        with self.lock:
            self.aborted = True
            sockets = tuple(self.active_sockets)
        for sock in sockets:
            self.interrupt(sock)

    def call(
        self,
        method,
        path,
        body=None,
        *,
        expected=(200,),
        credential=True,
        headers=None,
        deadline=None,
    ):
        started = time.monotonic()
        due = min(self.deadline, started + POLICY["request_timeout_seconds"])
        if deadline is not None:
            due = min(due, finite(deadline, positive=True))
        remaining = due - started
        if remaining <= 0:
            raise TimeoutError("Local assessment deadline exceeded.")
        fields = {"Content-Type": "application/json", **(headers or {})}
        if credential:
            fields["Authorization"] = "Bearer " + self.token
        raw = None if body is None else json.dumps(body, allow_nan=False).encode()
        connection = http.client.HTTPConnection(POLICY["host"], self.port, timeout=remaining)
        sock = timer = None
        expired = threading.Event()

        def check_deadline():
            if expired.is_set() or time.monotonic() >= due:
                raise TimeoutError("Absolute local HTTP deadline exceeded.")

        def expire():
            expired.set()
            self.interrupt(sock)

        try:
            connection.connect()
            sock = connection.sock
            with self.lock:
                if self.aborted:
                    raise TimeoutError("Local HTTP probe was aborted.")
                self.active_sockets.add(sock)
            check_deadline()
            timer = threading.Timer(max(0, due - time.monotonic()), expire)
            timer.daemon = True
            timer.start()
            connection.request(method, path, raw, fields)
            response = connection.getresponse()
            raw = response.read(1048577)
            check_deadline()
            elapsed = time.monotonic() - started
            if response.status not in expected or len(raw) > 1048576:
                raise ValueError("Unexpected local HTTP outcome or oversized response.")
            if (
                response.getheader("Cache-Control") != "no-store"
                or response.getheader("X-Content-Type-Options") != "nosniff"
            ):
                raise ValueError("Missing response security headers.")
            if path == "/metrics":
                parsed = parse_metrics(raw.decode("utf-8"))
                check_deadline()
                return parsed, response.status, elapsed
            result = json.loads(raw)
            request_id = response.getheader("X-Request-ID")
            if (
                not isinstance(result, dict)
                or not re.fullmatch("[0-9a-f]{32}", request_id or "")
                or result.get("request_id") != request_id
            ):
                raise ValueError("Invalid HTTP response correlation or envelope.")
            check_deadline()
            with self.lock:
                if request_id in self.ids:
                    raise ValueError("Duplicate request identity.")
                self.ids.add(request_id)
                if path == "/v1/recommendations":
                    self.statuses[str(response.status)] += 1
            if response.status in (429, 503):
                code = result.get("error", {}).get("code")
                if code != ("rate_limited" if response.status == 429 else "busy"):
                    raise ValueError("Unexpected degradation or worker failure.")
                if not (response.getheader("Retry-After") or "").isdigit():
                    raise ValueError("Missing retry guidance.")
            return result, response.status, elapsed
        except OSError:
            check_deadline()
            raise
        except http.client.HTTPException:
            check_deadline()
            raise ValueError("Local HTTP transport failed before completion.") from None
        finally:
            if timer is not None:
                timer.cancel()
                if timer.ident is not None:
                    timer.join(timeout=1)
            connection.close()
            if sock is not None:
                with self.lock:
                    self.active_sockets.discard(sock)

    def recommend(self, row, manifest, pin, *, k=20, allow_rejections=False):
        result, status, elapsed = self.call(
            "POST",
            "/v1/recommendations",
            {"user_id": row["user_id"], "k": k},
            expected=(200, 429, 503) if allow_rejections else (200,),
        )
        prediction = None
        if status == 200:
            checked = check_response(result, row, manifest, pin, k, "disabled")
            prediction = digest(checked)
            with self.lock:
                self.outputs.append(prediction)
        return {
            "status": status,
            "cohort": "cold" if row["user_id"] is None else "warm",
            "elapsed_seconds": elapsed,
            "prediction_sha256": prediction,
        }

    def reconcile(self):
        self.call("GET", "/health/ready")
        metrics, _, _ = self.call("GET", "/metrics")
        statuses = {
            status: int(
                value(
                    metrics, "recsys_http_requests_total", endpoint="recommendations", status=status
                )
            )
            for status in self.statuses
        }
        success = self.statuses["200"]
        if (
            statuses != dict(self.statuses)
            or value(metrics, "recsys_http_requests_total", endpoint="recommendations")
            != sum(self.statuses.values())
            or value(metrics, "recsys_primary_calls_total") != success
            or value(metrics, "recsys_primary_duration_seconds_count", outcome="success") != success
            or value(metrics, "recsys_deliveries_total") != success
            or value(metrics, "recsys_primary_in_flight") != 0
            or value(metrics, "recsys_ready") != 1
            or value(metrics, "recsys_observer_errors_total") != 0
            or value(metrics, "recsys_memory_sample_success") != 1
        ):
            raise ValueError("Client/worker/delivery telemetry failed reconciliation.")
        return {
            "recommendation_statuses": statuses,
            "primary_successes": success,
            "reconciled": True,
        }


class Resources:
    def __init__(self, child):
        self.child = child
        self.process = psutil.Process(child.pid)
        self.samples, self.errors = [], []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            while not self.done.is_set():
                self.samples.append((time.monotonic(), self.process.memory_info().rss))
                self.done.wait(POLICY["sample_interval_seconds"])
        except psutil.NoSuchProcess:
            if self.child.poll() is None:
                self.errors.append("Owned resource process disappeared.")
        except Exception:
            self.errors.append("Resource sampling failed.")

    def start(self):
        self.thread.start()

    def stop(self):
        self.done.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive() or self.errors:
            raise ValueError("Resource sampler did not finish successfully.")

    def summary(self, start, end):
        if self.errors:
            raise ValueError("Resource sampling failed.")
        selected = [(at, rss) for at, rss in self.samples if start <= at <= end]
        if len(selected) < 2 or any(type(rss) is not int or rss <= 0 for _, rss in selected):
            raise ValueError("Incomplete positive resource samples.")
        gaps = [selected[0][0] - start, end - selected[-1][0]]
        gaps += [b[0] - a[0] for a, b in zip(selected, selected[1:])]
        result = {
            "sample_count": len(selected),
            "duration_seconds": end - start,
            "maximum_gap_seconds": max(gaps),
            "peak_rss_bytes": max(rss for _, rss in selected),
        }
        validate_resources(result)
        return result


def validate_resources(row):
    require_object(
        row, {"sample_count", "peak_rss_bytes", "duration_seconds", "maximum_gap_seconds"}
    )
    if (
        not isinstance(row, dict)
        or type(row.get("sample_count")) is not int
        or row["sample_count"] < 2
        or type(row.get("peak_rss_bytes")) is not int
        or row["peak_rss_bytes"] <= 0
        or row["peak_rss_bytes"] > 2**63 - 1
    ):
        raise ValueError("Invalid resource sample counts or bytes.")
    duration = finite(row.get("duration_seconds"), positive=True)
    gap = finite(row.get("maximum_gap_seconds"), positive=True)
    if (
        gap > POLICY["maximum_sample_gap_seconds"]
        or duration > (row["sample_count"] + 1) * gap
        or row["sample_count"] > math.ceil(duration / POLICY["sample_interval_seconds"]) + 1
    ):
        raise ValueError("Resource coverage has missing or inconsistent samples.")


def require_object(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required).issubset(value)
        or not set(value).issubset(set(required) | set(optional))
    ):
        raise ValueError("Missing, unsupported or malformed receipt fields.")


def hash_value(value):
    if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Expected a SHA-256 identity.")


def validate_stop(row, *, ready, rejected=False):
    require_object(
        row,
        {
            "exit_code",
            "forced",
            "listener_closed",
            "cleanup_events",
            "startup_ready_events",
            "stop_seconds",
        },
    )
    if (
        type(row["exit_code"]) is not int
        or (row["exit_code"] == 0 if rejected else row["exit_code"] != 0)
        or row["forced"] is not False
        or row["listener_closed"] is not True
        or type(row["cleanup_events"]) is not int
        or row["cleanup_events"] != 1
        or type(row["startup_ready_events"]) is not int
        or row["startup_ready_events"] != ready
        or finite(row["stop_seconds"], positive=True) > POLICY["stop_deadline_seconds"]
    ):
        raise ValueError("Invalid process stop, readiness or cleanup evidence.")


def listener_closed(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex((POLICY["host"], port)) != 0


class OwnedServer:
    def __init__(self, bundle, pin, port, deadline):
        self.bundle, self.pin, self.port, self.deadline = bundle, pin, port, deadline
        self.child = self.log = self.sampler = None
        self.started = self.ready_at = None
        self.reaped = False
        self.token = secrets.token_urlsafe(32)
        fd, name = tempfile.mkstemp(prefix="local-release-", suffix=".log", dir=ROOT / ".local")
        self.log_path = Path(name)
        self.log = os.fdopen(fd, "wb")
        self.probe = Probe(port, self.token, deadline)

    def start(self, *, expect_ready=True):
        if self.child is not None:
            raise ValueError("Create a fresh owner for each process.")
        if not listener_closed(self.port):
            raise ValueError("Selected port is occupied; no foreign process will be stopped.")
        env = os.environ.copy()
        for name in ("RECSYS_API_TOKEN_FILE", "RECSYS_BUNDLE_PATH", "RECSYS_MANIFEST_SHA256"):
            env.pop(name, None)
        env["RECSYS_API_TOKEN"] = self.token
        env.update(
            dict.fromkeys(("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"), "1")
        )
        self.started = time.monotonic()
        self.child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scripts.serve_local_snapshot",
                "--bundle-path",
                str(self.bundle),
                "--manifest-sha256",
                self.pin,
                "--port",
                str(self.port),
                "--control-stdin",
            ],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=self.log,
            stderr=self.log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if not expect_ready:
            return
        self.sampler = Resources(self.child)
        self.sampler.start()
        limit = min(self.deadline, self.started + POLICY["startup_deadline_seconds"])
        while time.monotonic() < limit:
            if self.child.poll() is not None:
                raise ValueError("Owned API exited before readiness.")
            try:
                self.probe.call("GET", "/health/ready", deadline=limit)
                self.ready_at = time.monotonic()
                listeners = psutil.Process(self.child.pid).net_connections(kind="tcp")
                if not any(
                    c.status == psutil.CONN_LISTEN
                    and c.laddr.ip == POLICY["host"]
                    and c.laddr.port == self.port
                    for c in listeners
                ):
                    raise ValueError("Ready port does not belong to the owned API.")
                return
            except OSError:
                time.sleep(0.05)
        raise TimeoutError("Local API readiness timed out.")

    def stop(self, *, graceful=False):
        stop_started = time.monotonic()
        sampler_error = None
        if self.sampler:
            try:
                self.sampler.stop()
            except Exception as error:
                sampler_error = error
        forced = False
        try:
            if self.child is not None:
                if self.child.poll() is None:
                    try:
                        if graceful:
                            try:
                                if not self.child.stdin.closed:
                                    self.child.stdin.write(b"stop\n")
                                    self.child.stdin.flush()
                            except (OSError, ValueError):
                                # A closed pipe already delivers EOF. Still wait/reap,
                                # then force-stop on deadline if the worker fails to drain.
                                try:
                                    self.child.stdin.close()
                                except (OSError, ValueError):
                                    pass
                        else:
                            self.child.terminate()
                            forced = True
                        self.child.wait(timeout=POLICY["stop_deadline_seconds"])
                    except (OSError, subprocess.TimeoutExpired):
                        self.child.kill()
                        self.child.wait(timeout=10)
                        forced = True
                else:
                    self.child.wait(timeout=1)
                self.reaped = True
                try:
                    self.child.stdin.close()
                except (OSError, ValueError):
                    if self.child.poll() is None:
                        raise
        finally:
            self.log.close()
        if sampler_error:
            raise sampler_error
        if self.child is None:
            return None
        events = []
        for line in self.log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event.get("event"))
        result = {
            "exit_code": self.child.returncode,
            "forced": forced,
            "listener_closed": listener_closed(self.port),
            "cleanup_events": events.count("cleanup_complete"),
            "startup_ready_events": events.count("startup_ready"),
            "stop_seconds": time.monotonic() - stop_started,
        }
        if not result["listener_closed"]:
            raise ValueError("Owned API listener remains after cleanup.")
        if graceful and (forced or result["exit_code"] != 0 or result["cleanup_events"] != 1):
            raise ValueError("Graceful local shutdown was not verified.")
        return result

    def needs_cleanup(self):
        return (self.child is not None and not self.reaped) or not self.log.closed


def phase_summary(rows, arrivals, rate, elapsed, lateness, resources):
    if len(rows) != arrivals:
        raise ValueError("Missing or duplicate workload arrivals.")
    counts = Counter(str(row["status"]) for row in rows)
    timing = {}
    cohorts = Counter(row["cohort"] for row in rows)
    for cohort in ("warm", "cold"):
        values = [
            finite(row["elapsed_seconds"], positive=True)
            for row in rows
            if row["cohort"] == cohort and row["status"] == 200
        ]
        timing[cohort] = latency_metrics(values)
    return {
        "offered": arrivals,
        "completed": len(rows),
        "rate_per_second": rate,
        "cohorts": {name: cohorts[name] for name in ("warm", "cold")},
        "statuses": dict(sorted(counts.items())),
        "latency": timing,
        "duration_seconds": elapsed,
        "maximum_dispatch_lateness_seconds": max(lateness),
        "resources": resources,
    }


def workload(server, rows, manifest, pin, name):
    policy = POLICY[name]
    if len(rows) != policy["arrivals"]:
        raise ValueError("Workload request count differs from policy.")
    started, late, futures = time.monotonic(), [], []

    def invoke(row, scheduled):
        actual = time.monotonic()
        result = server.probe.recommend(row, manifest, pin, allow_rejections=True)
        return result, max(0, actual - scheduled)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=POLICY["client_workers"])
    completed = False
    try:
        for index, row in enumerate(rows):
            due = started + index / policy["rate"]
            if due >= server.deadline or time.monotonic() >= server.deadline:
                raise TimeoutError("Workload exceeds assessment deadline.")
            for future in futures:
                if future.done():
                    future.result()
            time.sleep(max(0, due - time.monotonic()))
            futures.append(pool.submit(invoke, row, due))
        results = []
        for future in futures:
            result, lateness = future.result(
                timeout=max(
                    0,
                    min(POLICY["request_timeout_seconds"] + 1, server.deadline - time.monotonic()),
                )
            )
            results.append(result)
            late.append(lateness)
        completed = True
    finally:
        if not completed:
            server.probe.abort()
        pool.shutdown(wait=False, cancel_futures=True)
        if not completed:
            concurrent.futures.wait(futures, timeout=1)
    end = time.monotonic()
    return phase_summary(
        results,
        len(rows),
        policy["rate"],
        end - started,
        late,
        server.sampler.summary(started, end),
    )


def assess(bundle, pin):
    manifest, references, reference_sha = reference_inputs(bundle, pin)
    warm = [row for row in references if row["user_id"] is not None]
    cold = [row for row in references if row["user_id"] is None]
    if (
        len(warm) != 100
        or len(cold) != 1
        or any(row["trace"]["route"] != "hybrid_learned" for row in warm)
    ):
        raise ValueError("Complete sealed 100-warm/one-cold references required.")
    verify_inventory(bundle, pin)
    before, system = identity(), runtime()
    assessment_started = time.monotonic()
    deadline = assessment_started + POLICY["overall_deadline_seconds"]
    with socket.socket() as reservation:
        reservation.bind((POLICY["host"], 0))
        port = reservation.getsockname()[1]
    owners, runs = [], []
    try:
        for index in range(2):
            server = OwnedServer(bundle, pin, port, deadline)
            owners.append(server)
            server.start()
            reference_digests = []
            for row in references:
                reference_digests.append(
                    server.probe.recommend(row, manifest, pin)["prediction_sha256"]
                )
                time.sleep(0.26)
            if index == 0:
                for row in (warm[0], cold[0]):
                    for k in (5, 10, 20):
                        server.probe.recommend(row, manifest, pin, k=k)
                        time.sleep(0.26)
                for body in ({"k": 0}, {"k": 21}, {"k": True}, {"history": ["private"]}):
                    server.probe.call("POST", "/v1/recommendations", body, expected=(422,))
                    time.sleep(0.26)
                server.probe.call("GET", "/health/ready", credential=False, expected=(401,))
                server.probe.call(
                    "POST", "/v1/recommendations", {}, credential=False, expected=(401,)
                )
                time.sleep(0.26)
                server.probe.call(
                    "POST",
                    "/v1/recommendations",
                    {},
                    headers={"Host": "foreign.invalid"},
                    expected=(400,),
                )
                time.sleep(0.26)
                server.probe.call(
                    "POST", "/v1/recommendations", {}, headers={"Origin": "null"}, expected=(403,)
                )
                # Each sixth offered request is cold; every warm reference appears once.
                steady_rows, at = [], 0
                for i in range(POLICY["steady"]["arrivals"]):
                    steady_rows.append(cold[0] if (i + 1) % 6 == 0 else warm[at])
                    at += (i + 1) % 6 != 0
                steady = workload(server, steady_rows, manifest, pin, "steady")
                server.probe.reconcile()
                burst = workload(
                    server,
                    [warm[i] for i in range(POLICY["burst"]["arrivals"])],
                    manifest,
                    pin,
                    "burst",
                )
                recovery_start = time.monotonic()
                time.sleep(POLICY["recovery_refill_seconds"])
                for row in (warm[0], cold[0]):
                    server.probe.recommend(row, manifest, pin)
                recovery = time.monotonic() - recovery_start
            telemetry = server.probe.reconcile()
            end = time.monotonic()
            run = {
                "reference_counts": {"warm": len(warm), "cold": len(cold)},
                "sealed_reference_outputs_sha256": digest(reference_digests),
                "reference_output_digests_sha256": digest(sorted(server.probe.outputs)),
                "startup_seconds": server.ready_at - server.started,
                "startup_resources": server.sampler.summary(server.started, server.ready_at),
                "loaded_resources": server.sampler.summary(server.ready_at, end),
                "telemetry": telemetry,
            }
            run["stop"] = server.stop(graceful=True)
            runs.append(run)
        invalid = OwnedServer(bundle, "0" * 64 if pin != "0" * 64 else "1" * 64, port, deadline)
        owners.append(invalid)
        invalid.start(expect_ready=False)
        invalid.child.wait(
            timeout=min(POLICY["startup_deadline_seconds"], max(0.01, deadline - time.monotonic()))
        )
        rejection = invalid.stop()
        if rejection["exit_code"] == 0 or rejection["startup_ready_events"] != 0:
            raise ValueError("Wrong manifest startup was not rejected before readiness.")
        early = OwnedServer(bundle, pin, port, deadline)
        owners.append(early)
        early.start(expect_ready=False)
        early.child.stdin.close()
        early_stop = early.stop(graceful=True)
        if early_stop["startup_ready_events"] != 0:
            raise ValueError("Early control EOF published late readiness.")
    finally:
        errors = []
        for owner in reversed(owners):
            if owner.needs_cleanup():
                try:
                    owner.stop()
                except Exception:
                    errors.append("Owned cleanup failed.")
        if errors:
            raise ValueError("Could not clean up every owned process.")
    verify_inventory(bundle, pin)
    if before != identity() or system != runtime():
        raise ValueError("Source or environment changed during local qualification.")
    result = {
        "schema_version": 1,
        "verification": VERIFICATION,
        "policy": POLICY,
        "sources_sha256_lf": before,
        "runtime": system,
        "manifest_sha256": pin,
        "references_sha256": reference_sha,
        "runs": runs,
        "steady": steady,
        "burst": burst,
        "recovery_seconds": recovery,
        "invalid_manifest_startup": rejection,
        "early_control_stop": early_stop,
        "assessment_seconds": time.monotonic() - assessment_started,
        "public_inference": False,
        "cloud_deployed": False,
        "graceful_inflight_drain_measured": False,
        "scope": POLICY["scope"],
    }
    result.update(acceptance(result))
    result["content_sha256"] = digest(result)
    return result


def validate_phase(row, name):
    require_object(
        row,
        {
            "offered",
            "completed",
            "rate_per_second",
            "cohorts",
            "statuses",
            "latency",
            "duration_seconds",
            "maximum_dispatch_lateness_seconds",
            "resources",
        },
    )
    require_object(row["cohorts"], {"warm", "cold"})
    require_object(row["latency"], {"warm", "cold"})
    expected = POLICY[name]
    if not isinstance(row, dict) or any(
        type(row.get(k)) is not int or row[k] != expected["arrivals"]
        for k in ("offered", "completed")
    ):
        raise ValueError("Incomplete workload arrivals.")
    if (
        type(row.get("rate_per_second")) is not int
        or row["rate_per_second"] != expected["rate"]
        or row.get("cohorts") != {k: expected[k] for k in ("warm", "cold")}
        or any(type(row["cohorts"][k]) is not int for k in ("warm", "cold"))
    ):
        raise ValueError("Foreign rate or cohort mix.")
    statuses = row.get("statuses")
    if (
        not isinstance(statuses, dict)
        or not set(statuses).issubset({"200", "429", "503"})
        or any(type(n) is not int or n <= 0 for n in statuses.values())
        or sum(statuses.values()) != expected["arrivals"]
    ):
        raise ValueError("Invalid workload status accounting.")
    if (
        finite(row.get("duration_seconds"), positive=True)
        < (expected["arrivals"] - 1) / expected["rate"]
    ):
        raise ValueError("Workload ended before all scheduled arrivals.")
    if finite(row.get("maximum_dispatch_lateness_seconds")) > row["duration_seconds"]:
        raise ValueError("Dispatch lateness exceeds the workload interval.")
    validate_resources(row["resources"])
    if abs(row["resources"]["duration_seconds"] - row["duration_seconds"]) > 1e-6:
        raise ValueError("Resource samples cover a different workload interval.")
    count = 0
    for cohort in ("warm", "cold"):
        stats = row["latency"][cohort]
        require_object(
            stats,
            {
                "latency_samples",
                "latency_avg_ms",
                "latency_p50_ms",
                "latency_p95_ms",
                "latency_p99_ms",
            },
        )
        n = stats.get("latency_samples")
        if type(n) is not int or not 0 <= n <= expected[cohort]:
            raise ValueError("Invalid cohort latency count.")
        values = [finite(stats.get("latency_p" + str(q) + "_ms")) for q in (50, 95, 99)]
        average = finite(stats.get("latency_avg_ms"))
        if max(average, *values) > row["duration_seconds"] * 1000 + 1e-6:
            raise ValueError("Request latency exceeds its containing workload interval.")
        if (
            values != sorted(values)
            or (n == 0 and any([average, *values]))
            or (n > 0 and (values[0] <= 0 or average <= 0))
        ):
            raise ValueError("Invalid successful latency summary.")
        count += n
    if count != statuses.get("200", 0):
        raise ValueError("Latency counts include rejected or missing requests.")


def acceptance(result):
    require_object(
        result,
        {
            "schema_version",
            "verification",
            "policy",
            "sources_sha256_lf",
            "runtime",
            "manifest_sha256",
            "references_sha256",
            "runs",
            "steady",
            "burst",
            "recovery_seconds",
            "invalid_manifest_startup",
            "early_control_stop",
            "assessment_seconds",
            "public_inference",
            "cloud_deployed",
            "graceful_inflight_drain_measured",
            "scope",
        },
        {
            "assessment_completed",
            "operational_passed",
            "targets",
            "local_release_accepted",
            "public_deployment_eligible",
            "content_sha256",
        },
    )
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise ValueError("Unsupported local receipt schema.")
    if (
        digest(result.get("policy")) != digest(POLICY)
        or result.get("verification") != VERIFICATION
        or result["scope"] != POLICY["scope"]
        or any(
            result[name] is not False
            for name in ("public_inference", "cloud_deployed", "graceful_inflight_drain_measured")
        )
    ):
        raise ValueError("Foreign local-release policy.")
    for name in ("manifest_sha256", "references_sha256"):
        hash_value(result[name])
    if (
        not isinstance(result["sources_sha256_lf"], dict)
        or not result["sources_sha256_lf"]
        or not isinstance(result["runtime"], dict)
        or not result["runtime"]
    ):
        raise ValueError("Missing source or runtime identity.")
    for name, pin in result["sources_sha256_lf"].items():
        if type(name) is not str or not name:
            raise ValueError("Invalid source identity.")
        hash_value(pin)
    if any(
        type(name) is not str or type(v) is not str or not v
        for name, v in result["runtime"].items()
    ):
        raise ValueError("Invalid runtime identity.")
    if finite(result.get("assessment_seconds"), positive=True) > POLICY["overall_deadline_seconds"]:
        raise ValueError("Overall assessment deadline exceeded.")
    runs = result.get("runs")
    if not isinstance(runs, list) or len(runs) != 2:
        raise ValueError("Initial and restarted process required.")
    for run in runs:
        require_object(
            run,
            {
                "reference_counts",
                "sealed_reference_outputs_sha256",
                "reference_output_digests_sha256",
                "startup_seconds",
                "startup_resources",
                "loaded_resources",
                "telemetry",
                "stop",
            },
        )
        if run.get("reference_counts") != POLICY["reference_counts"] or any(
            type(run["reference_counts"][k]) is not int for k in ("warm", "cold")
        ):
            raise ValueError("Incomplete initial/restart references.")
        finite(run.get("startup_seconds"), positive=True)
        if run["startup_seconds"] > POLICY["startup_deadline_seconds"]:
            raise ValueError("Startup exceeded policy.")
        for name in ("startup_resources", "loaded_resources"):
            validate_resources(run[name])
        if abs(run["startup_seconds"] - run["startup_resources"]["duration_seconds"]) > 1e-6:
            raise ValueError("Startup resource coverage differs from startup duration.")
        stop, telemetry = run["stop"], run["telemetry"]
        validate_stop(stop, ready=1)
        require_object(telemetry, {"recommendation_statuses", "primary_successes", "reconciled"})
        if telemetry.get("reconciled") is not True:
            raise ValueError("Local lifecycle or telemetry is incomplete.")
        hash_value(run["reference_output_digests_sha256"])
        hash_value(run["sealed_reference_outputs_sha256"])
    if runs[0]["sealed_reference_outputs_sha256"] != runs[1]["sealed_reference_outputs_sha256"]:
        raise ValueError("Restart changed sealed reference outputs.")
    for phase in ("steady", "burst"):
        validate_phase(result[phase], phase)
    rejection = result["invalid_manifest_startup"]
    validate_stop(rejection, ready=0, rejected=True)
    validate_stop(result["early_control_stop"], ready=0)
    recovery = finite(result.get("recovery_seconds"), positive=True)
    if recovery < POLICY["recovery_refill_seconds"]:
        raise ValueError("Recovery excludes the required quota refill interval.")
    steady, burst = result["steady"], result["burst"]
    containing = runs[0]["loaded_resources"]
    if containing["duration_seconds"] + 1e-6 < steady["duration_seconds"] + burst[
        "duration_seconds"
    ] + recovery or any(
        result[name]["resources"]["peak_rss_bytes"] > containing["peak_rss_bytes"]
        for name in ("steady", "burst")
    ):
        raise ValueError("Workload resources do not fit the containing loaded-process scope.")
    minimum = sum(
        run["startup_seconds"]
        + run["loaded_resources"]["duration_seconds"]
        + run["stop"]["stop_seconds"]
        for run in runs
    )
    minimum += rejection["stop_seconds"] + result["early_control_stop"]["stop_seconds"]
    if result["assessment_seconds"] + 1e-6 < minimum:
        raise ValueError("Assessment duration is shorter than its measured process phases.")
    success = burst["statuses"].get("200", 0)
    if not 0 < success < POLICY["burst"]["arrivals"]:
        raise ValueError("Overload must observe both successful and rejected requests.")
    expected_first = Counter(
        {
            "200": sum(POLICY["reference_counts"].values())
            + POLICY["prefix_calls"]
            + 2
            + steady["statuses"].get("200", 0)
            + success,
            "422": 4,
            "401": 1,
            "400": 1,
            "403": 1,
        }
    )
    for phase in (steady, burst):
        for status in ("429", "503"):
            expected_first[status] += phase["statuses"].get(status, 0)
    for run, expected in zip(runs, (dict(+expected_first), {"200": 101})):
        telemetry = run["telemetry"]
        if not isinstance(telemetry["recommendation_statuses"], dict) or any(
            type(v) is not int or v <= 0 for v in telemetry["recommendation_statuses"].values()
        ):
            raise ValueError("Invalid telemetry status counts.")
        if (
            telemetry.get("recommendation_statuses") != expected
            or type(telemetry.get("primary_successes")) is not int
            or telemetry["primary_successes"] != expected["200"]
        ):
            raise ValueError("Aggregate telemetry differs from complete request coverage.")
    targets = {
        "steady_no_rejections": steady["statuses"] == {"200": POLICY["steady"]["arrivals"]},
        "steady_warm_p95": steady["latency"]["warm"]["latency_p95_ms"]
        <= POLICY["warm_p95_target_ms"]
        and steady["latency"]["warm"]["latency_samples"] > 0,
        "steady_warm_p99": steady["latency"]["warm"]["latency_p99_ms"]
        <= POLICY["warm_p99_target_ms"]
        and steady["latency"]["warm"]["latency_samples"] > 0,
        "steady_dispatch": steady["maximum_dispatch_lateness_seconds"]
        <= POLICY["maximum_dispatch_lateness_seconds"],
        "burst_dispatch": burst["maximum_dispatch_lateness_seconds"]
        <= POLICY["maximum_dispatch_lateness_seconds"],
        "loaded_process_memory": max(run["loaded_resources"]["peak_rss_bytes"] for run in runs)
        <= POLICY["loaded_rss_target_bytes"],
        "recovery": recovery <= POLICY["recovery_deadline_seconds"],
    }
    derived = {
        "assessment_completed": True,
        "operational_passed": True,
        "targets": targets,
        "local_release_accepted": all(targets.values()),
        "public_deployment_eligible": False,
    }
    for name in (
        "assessment_completed",
        "operational_passed",
        "local_release_accepted",
        "public_deployment_eligible",
    ):
        if name in result and type(result[name]) is not bool:
            raise ValueError("Acceptance flags must be booleans.")
    if "targets" in result:
        require_object(result["targets"], set(targets))
        if any(type(v) is not bool for v in result["targets"].values()):
            raise ValueError("Target outcomes must be booleans.")
    return derived


def read_receipt(path):
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > 2 * 1024**2
    ):
        raise ValueError("Expected a bounded regular receipt file.")

    def unique(pairs):
        fields = {}
        for key, item in pairs:
            if key in fields:
                raise ValueError("Duplicate receipt field.")
            fields[key] = item
        return fields

    def reject_constant(value):
        raise ValueError("Nonfinite receipt number.")

    def parse_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite receipt number.")
        return number

    try:
        with path.open("rb") as stream:
            data = stream.read(2 * 1024**2 + 1)
        if len(data) > 2 * 1024**2:
            raise ValueError("Oversized receipt file.")
        result = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Malformed UTF-8 receipt.") from error
    if not isinstance(result, dict):
        raise ValueError("Receipt must be an object.")
    return result


def check_receipt(bundle, pin, path):
    saved = read_receipt(path)
    if saved.get("content_sha256") != digest(
        {k: v for k, v in saved.items() if k != "content_sha256"}
    ):
        raise ValueError("Invalid local-release checksum.")
    classifications = acceptance(saved)
    verify_inventory(bundle, pin)
    manifest, references, reference_sha = reference_inputs(bundle, pin)
    if (
        saved.get("sources_sha256_lf") != identity()
        or saved.get("runtime") != runtime()
        or saved.get("manifest_sha256") != pin
        or saved.get("references_sha256") != reference_sha
    ):
        raise ValueError("Local release source, environment or input identity changed.")
    expected = digest(
        [
            digest(
                {
                    "items": row["trace"]["output"],
                    "route": row["trace"]["route"],
                    "bundle_version": manifest["bundle_version"],
                    "cutoff": manifest["snapshot"]["cutoff"],
                }
            )
            for row in references
        ]
    )
    if any(run.get("sealed_reference_outputs_sha256") != expected for run in saved.get("runs", [])):
        raise ValueError("Reference-output identity differs from the sealed input.")
    for key, expected in classifications.items():
        if saved.get(key) != expected:
            raise ValueError("Saved local acceptance classification differs.")
    if (
        saved.get("cloud_deployed") is not False
        or saved.get("public_inference") is not False
        or saved.get("graceful_inflight_drain_measured") is not False
    ):
        raise ValueError("Unsupported qualification scope.")
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{64}", args.manifest_sha256):
        parser.error("Supply the trusted lowercase manifest SHA-256.")
    try:
        if args.check:
            result = check_receipt(args.bundle.resolve(), args.manifest_sha256, args.check)
        else:
            validate_output_path(args.output)
            if args.output.exists():
                raise ValueError("Keep earlier local-release evidence unchanged.")
            (ROOT / ".local").mkdir(exist_ok=True)
            result = assess(args.bundle.resolve(), args.manifest_sha256)
            publish(args.output, result)
    except (ValueError, OSError, RuntimeError, TimeoutError, subprocess.SubprocessError):
        parser.exit(2, "Local release verification failed; inspect private logs.\n")
    print(
        json.dumps(
            {
                name: result[name]
                for name in (
                    "assessment_completed",
                    "operational_passed",
                    "targets",
                    "local_release_accepted",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
