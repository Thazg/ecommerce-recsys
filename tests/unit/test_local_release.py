"""Local acceptance fails closed on incomplete scope, ownership and provenance."""

import copy
import io
import json
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from ecommerce_recsys.artifacts.contract import digest
from scripts import serve_local_snapshot as launcher
from scripts import verify_local_release as gate


def resource(duration=120, rss=1600000000):
    return {
        "sample_count": int(duration / 0.05) + 1,
        "duration_seconds": duration,
        "maximum_gap_seconds": 0.05,
        "peak_rss_bytes": rss,
    }


def phase(name):
    settings = gate.POLICY[name]
    rows = [{"status": 200, "cohort": "warm", "elapsed_seconds": 0.1}] * settings["warm"]
    rows += [{"status": 200, "cohort": "cold", "elapsed_seconds": 0.01}] * settings["cold"]
    if name == "burst":
        rows = rows[:8] + [{"status": 503, "cohort": "warm", "elapsed_seconds": 0.001}] * 12
        rows += [{"status": 429, "cohort": "warm", "elapsed_seconds": 0.001}] * 12
    seconds = settings["arrivals"] / settings["rate"]
    return gate.phase_summary(
        rows,
        settings["arrivals"],
        settings["rate"],
        seconds,
        [0.002] * len(rows),
        resource(seconds),
    )


@pytest.fixture
def receipt():
    runs = []
    for statuses in (
        {"200": 237, "422": 4, "401": 1, "400": 1, "403": 1, "503": 12, "429": 12},
        {"200": 101},
    ):
        runs.append(
            {
                "reference_counts": {"warm": 100, "cold": 1},
                "startup_seconds": 10,
                "startup_resources": resource(10),
                "loaded_resources": resource(200),
                "reference_output_digests_sha256": "a" * 64,
                "sealed_reference_outputs_sha256": "b" * 64,
                "stop": {
                    "exit_code": 0,
                    "forced": False,
                    "listener_closed": True,
                    "cleanup_events": 1,
                    "startup_ready_events": 1,
                    "stop_seconds": 0.1,
                },
                "telemetry": {
                    "recommendation_statuses": statuses,
                    "primary_successes": statuses["200"],
                    "reconciled": True,
                },
            }
        )
    runs[1]["loaded_resources"] = resource(40)
    result = {
        "schema_version": 1,
        "verification": gate.VERIFICATION,
        "policy": copy.deepcopy(gate.POLICY),
        "runs": runs,
        "steady": phase("steady"),
        "burst": phase("burst"),
        "assessment_seconds": 300,
        "sources_sha256_lf": {"fixture": "c" * 64},
        "runtime": {"python": "fixture"},
        "manifest_sha256": "a" * 64,
        "references_sha256": "b" * 64,
        "scope": gate.POLICY["scope"],
        "recovery_seconds": 2.3,
        "invalid_manifest_startup": {
            "exit_code": 3,
            "listener_closed": True,
            "startup_ready_events": 0,
            "cleanup_events": 1,
            "stop_seconds": 0.1,
            "forced": False,
        },
        "public_inference": False,
        "cloud_deployed": False,
        "graceful_inflight_drain_measured": False,
    }
    result["early_control_stop"] = {
        "exit_code": 0,
        "forced": False,
        "listener_closed": True,
        "startup_ready_events": 0,
        "cleanup_events": 1,
        "stop_seconds": 0.1,
    }
    result.update(gate.acceptance(result))
    return result


@pytest.mark.parametrize("command", ["stop\n", "", "unrecognized\n"])
def test_owned_pipe_requests_graceful_server_exit(command):
    stop_requested = threading.Event()
    launcher.watch_control_pipe(io.StringIO(command), stop_requested)
    assert stop_requested.is_set()


def test_broken_control_reader_also_requests_owned_stop():
    stop_requested = threading.Event()

    class Broken:
        def readline(self, limit):
            raise OSError("pipe closed")

    launcher.watch_control_pipe(Broken(), stop_requested)
    assert stop_requested.is_set()


def test_control_rejects_non_pipe_before_loading_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "stdin", io.StringIO("stop\n"))
    with pytest.raises(SystemExit) as error:
        launcher.main(
            ["--bundle-path", str(tmp_path), "--manifest-sha256", "a" * 64, "--control-stdin"]
        )
    assert error.value.code == 2


def test_target_failure_is_recorded_without_fabricating_operational_failure(receipt):
    receipt["runs"][0]["loaded_resources"]["peak_rss_bytes"] = 3 * 1024**3
    receipt["steady"]["latency"]["warm"]["latency_p99_ms"] = 700
    result = gate.acceptance(receipt)
    assert result["assessment_completed"] and result["operational_passed"]
    assert not result["local_release_accepted"]
    assert not result["targets"]["loaded_process_memory"]
    assert not result["targets"]["steady_warm_p99"]
    assert not result["public_deployment_eligible"]


def test_steady_rejection_is_a_budget_failure_with_complete_accounting(receipt):
    steady = receipt["steady"]
    steady["statuses"] = {"200": 119, "503": 1}
    steady["latency"]["warm"]["latency_samples"] = 99
    telemetry = receipt["runs"][0]["telemetry"]
    telemetry["recommendation_statuses"].update({"200": 236, "503": 13})
    telemetry["primary_successes"] = 236
    result = gate.acceptance(receipt)
    assert result["assessment_completed"] and not result["targets"]["steady_no_rejections"]
    assert not result["local_release_accepted"]


@pytest.mark.parametrize(
    "number",
    [True, float("inf"), float("nan"), 10**10000, -1],
    ids=["bool", "infinity", "nan", "huge-integer", "negative"],
)
def test_invalid_numbers_fail_with_a_controlled_error(number):
    with pytest.raises(ValueError):
        gate.finite(number)


def test_policy_numeric_booleans_are_not_equivalent(receipt):
    receipt["policy"]["numeric_threads"] = True
    with pytest.raises(ValueError, match="policy"):
        gate.acceptance(receipt)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["runs"].pop(),
        lambda r: r["runs"][0]["reference_counts"].update(cold=True),
        lambda r: r["runs"][0]["stop"].update(forced=True),
        lambda r: r["runs"][0]["stop"].update(cleanup_events=2),
        lambda r: r["runs"][1]["stop"].update(listener_closed=False),
        lambda r: r["runs"][1].update(sealed_reference_outputs_sha256="c" * 64),
        lambda r: r["runs"][1]["telemetry"].update(primary_successes=100),
        lambda r: r["steady"].update(completed=119),
        lambda r: r["steady"].update(rate_per_second=True),
        lambda r: r["steady"]["statuses"].update({"500": 1}),
        lambda r: r["steady"]["latency"]["warm"].update(latency_samples=99),
        lambda r: r["steady"]["resources"].update(duration_seconds=100),
        lambda r: r["burst"]["latency"]["cold"].update(latency_avg_ms=1),
        lambda r: r["invalid_manifest_startup"].update(startup_ready_events=1),
        lambda r: r["invalid_manifest_startup"].update(forced=True),
        lambda r: r.update(assessment_seconds=601),
        lambda r: r.update(recovery_seconds=float("nan")),
    ],
)
def test_incomplete_or_inconsistent_acceptance_fails(receipt, mutation):
    mutation(receipt)
    with pytest.raises(ValueError):
        gate.acceptance(receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("peak_rss_bytes", True),
        ("peak_rss_bytes", 1.1),
        ("sample_count", 1),
        ("maximum_gap_seconds", 0.3),
        ("duration_seconds", float("nan")),
        ("sample_count", 2),
    ],
)
def test_resource_bounds_and_sampling_coverage_are_required(field, value):
    row = resource()
    row[field] = value
    with pytest.raises(ValueError):
        gate.validate_resources(row)


def test_real_phase_summary_excludes_fast_rejections_from_latency():
    row = phase("burst")
    assert row["statuses"] == {"200": 8, "429": 12, "503": 12}
    assert row["latency"]["warm"]["latency_samples"] == 8
    assert row["latency"]["warm"]["latency_p95_ms"] == 100
    gate.validate_phase(row, "burst")


def test_source_fingerprint_changes_when_dependency_inventory_changes(monkeypatch):
    original = gate.identity()
    monkeypatch.setattr(gate, "sources", lambda: {"sentinel.py": "1" * 64})
    assert gate.identity() != original


def test_resource_sampler_failure_still_reaps_the_owned_child(tmp_path, monkeypatch):
    owner = object.__new__(gate.OwnedServer)
    owner.port = 12345
    owner.log_path = tmp_path / "owned.log"
    owner.log = owner.log_path.open("wb")

    class BrokenSampler:
        def stop(self):
            raise RuntimeError("sampler setup failed")

    class Child:
        returncode = None
        stdin = io.BytesIO()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def wait(self, timeout):
            return self.returncode

    owner.sampler, owner.child = BrokenSampler(), Child()
    monkeypatch.setattr(gate, "listener_closed", lambda port: True)
    with pytest.raises(RuntimeError):
        owner.stop()
    assert owner.child.returncode == 1 and owner.child.stdin.closed and owner.log.closed


def test_receipt_is_exclusive_and_sealed(tmp_path, receipt):
    target = tmp_path / "receipt.json"
    receipt["content_sha256"] = digest(receipt)
    gate.publish(target, receipt)
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        gate.publish(target, receipt)
    assert target.read_bytes() == before
    bad = dict(receipt, content_sha256="0" * 64)
    with pytest.raises(ValueError):
        gate.publish(tmp_path / "bad.json", bad)
    assert len(list(tmp_path.glob("*.tmp"))) == 0


def test_saved_receipt_rejects_wrong_source_and_acceptance_claims(tmp_path, receipt, monkeypatch):
    manifest = {"bundle_version": "fixture-v1", "snapshot": {"cutoff": 5}}
    references = [{"trace": {"output": [], "route": "hybrid_learned"}}]
    expected = digest(
        [
            digest(
                {
                    "items": [],
                    "route": "hybrid_learned",
                    "bundle_version": "fixture-v1",
                    "cutoff": 5,
                }
            )
        ]
    )
    for run in receipt["runs"]:
        run["sealed_reference_outputs_sha256"] = expected
    receipt.update(
        manifest_sha256="a" * 64,
        references_sha256="b" * 64,
        sources_sha256_lf={"fixture": "c" * 64},
        runtime={"python": "fixture"},
    )
    monkeypatch.setattr(gate, "verify_inventory", lambda *args: None)
    monkeypatch.setattr(gate, "reference_inputs", lambda *args: (manifest, references, "b" * 64))
    monkeypatch.setattr(gate, "identity", lambda: {"fixture": "c" * 64})
    monkeypatch.setattr(gate, "runtime", lambda: {"python": "fixture"})
    path = tmp_path / "receipt.json"

    def save():
        payload = {k: v for k, v in receipt.items() if k != "content_sha256"}
        payload["content_sha256"] = digest(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")

    save()
    assert gate.check_receipt(tmp_path, "a" * 64, path)["local_release_accepted"]
    receipt["local_release_accepted"] = False
    save()
    with pytest.raises(ValueError, match="classification"):
        gate.check_receipt(tmp_path, "a" * 64, path)
    receipt["local_release_accepted"] = True
    receipt["sources_sha256_lf"] = {"changed": "d" * 64}
    save()
    with pytest.raises(ValueError, match="identity"):
        gate.check_receipt(tmp_path, "a" * 64, path)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["steady"]["resources"].update(peak_rss_bytes=3 * 1024**3),
        lambda r: r["runs"][0]["startup_resources"].update(duration_seconds=9),
        lambda r: r["runs"][0].update(loaded_resources=resource(1)),
        lambda r: r.update(assessment_seconds=1),
        lambda r: r["runs"][0]["stop"].update(exit_code=False),
        lambda r: r["runs"][0]["stop"].update(startup_ready_events=True),
        lambda r: r["early_control_stop"].update(startup_ready_events=1),
        lambda r: r.update(schema_version=True),
        lambda r: r.update(local_release_accepted=1),
        lambda r: r["steady"].pop("latency"),
        lambda r: r["runs"].__setitem__(0, None),
        lambda r: r["steady"].update(latency=[]),
        lambda r: r.update(scope="public production"),
        lambda r: r.update(unsupported_claim=True),
    ],
)
def test_audited_receipt_contradictions_and_types_are_rejected(receipt, mutation):
    mutation(receipt)
    with pytest.raises(ValueError):
        gate.acceptance(receipt)


def test_closed_control_pipe_still_waits_and_reaps(tmp_path, monkeypatch):
    owner = object.__new__(gate.OwnedServer)
    owner.port, owner.sampler, owner.reaped = 12345, None, False
    owner.log_path = tmp_path / "owned.log"
    owner.log = owner.log_path.open("wb")
    owner.log.write(b'{"event":"startup_ready"}\n{"event":"cleanup_complete"}\n')

    class Child:
        returncode = None
        waited = False
        stdin = io.BytesIO()

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.waited, self.returncode = True, 0

    owner.child = Child()
    owner.child.stdin.close()
    monkeypatch.setattr(gate, "listener_closed", lambda port: True)
    result = owner.stop(graceful=True)
    assert owner.child.waited and owner.reaped and not owner.needs_cleanup()
    assert result["exit_code"] == 0 and not result["forced"]


def test_failed_reap_remains_owned_even_after_log_closed(tmp_path, monkeypatch):
    owner = object.__new__(gate.OwnedServer)
    owner.port, owner.sampler, owner.reaped = 12345, None, False
    owner.log_path = tmp_path / "owned.log"
    owner.log = owner.log_path.open("wb")

    class Child:
        returncode = None
        waits = 0
        stdin = io.BytesIO()

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            self.waits += 1
            if self.waits < 3:
                raise subprocess.TimeoutExpired("owned", timeout)
            self.returncode = 1

        def kill(self):
            pass

        def terminate(self):
            pass

    owner.child = Child()
    monkeypatch.setattr(gate, "listener_closed", lambda port: True)
    with pytest.raises(subprocess.TimeoutExpired):
        owner.stop(graceful=True)
    assert owner.log.closed and owner.needs_cleanup()
    owner.stop()
    assert owner.reaped and not owner.needs_cleanup()


def test_absolute_http_deadline_interrupts_a_dripping_body():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve():
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(2)
                request = b""
                while b"\r\n\r\n" not in request:
                    part = connection.recv(4096)
                    if not part:
                        return
                    request += part
                body = json.dumps({"request_id": "a" * 32}).encode()
                connection.sendall(
                    (
                        "HTTP/1.1 200 OK\r\nCache-Control: no-store\r\n"
                        "X-Content-Type-Options: nosniff\r\nX-Request-ID: "
                        + "a" * 32
                        + "\r\nContent-Length: "
                        + str(len(body))
                        + "\r\n\r\n"
                    ).encode()
                )
                for byte in body:
                    connection.sendall(bytes([byte]))
                    time.sleep(0.02)
        except OSError:
            pass
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    probe = gate.Probe(port, "x" * 32, time.monotonic() + 0.15)
    try:
        with pytest.raises(TimeoutError):
            probe.call("GET", "/health/ready")
    finally:
        thread.join(timeout=3)
    assert not thread.is_alive() and not probe.active_sockets


def test_workload_failure_aborts_io_before_executor_cleanup(monkeypatch):
    release = threading.Event()

    class Probe:
        aborted = False

        def recommend(self, row, *args, **kwargs):
            if row == 0:
                release.wait(timeout=2.5)
                raise ValueError("held worker released")
            raise ValueError("failed worker")

        def abort(self):
            self.aborted = True
            release.set()

    settings = copy.deepcopy(gate.POLICY)
    settings["burst"].update(arrivals=2, rate=1000)
    settings["request_timeout_seconds"] = 0.01
    monkeypatch.setattr(gate, "POLICY", settings)
    probe = Probe()
    server = SimpleNamespace(probe=probe, deadline=time.monotonic() + 5)
    try:
        with pytest.raises((ValueError, TimeoutError)):
            gate.workload(server, [0, 1], {}, "a" * 64, "burst")
    finally:
        release.set()
    assert probe.aborted


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e9999}', "[]", "\ufeff{}"])
def test_strict_receipt_reader_rejects_malformed_inputs(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        gate.read_receipt(path)
