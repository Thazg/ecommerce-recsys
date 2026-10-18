"""Negative evidence and process-ownership checks for the integration gate."""

import copy
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest

from ecommerce_recsys.artifacts.contract import (
    digest,
    environment,
    file_sha,
    inference_code,
    runtime_code,
)
from scripts import release_validation as validation
from scripts import verify_release as release


def test_receipt_digest_duplicate_keys_nonfinite_and_shape(tmp_path):
    path = tmp_path / "receipt.json"
    release.publish(path, {"ok": True})
    assert validation.load_receipt(path)["ok"] is True
    for raw in ('{"ok":1,"ok":2}', '{"a":NaN}', "[]", '{"content_sha256":"wrong"}', "{"):
        path.write_text(raw)
        with pytest.raises(ValueError):
            validation.load_receipt(path)


def report(tmp_path, case, *, tests=1, skips=0, failures=0):
    path = tmp_path / "report.xml"
    case = case.replace('classname="x"', 'classname="tests.integration.test_snapshot_http"')
    path.write_text(
        f'<testsuites><testsuite tests="{tests}" errors="0" failures="{failures}" skipped="{skips}">{case}</testsuite></testsuites>'
    )
    return path


@pytest.mark.parametrize(
    "case,tests,skips,failures",
    [
        ("", 0, 0, 0),
        ('<testcase classname="x" name="y"/>', 2, 0, 0),
        ('<testcase classname="x" name="y"><failure/></testcase>', 1, 0, 1),
        (
            '<testcase classname="x" name="y"><skipped message="missing service dependency"/></testcase>',
            1,
            1,
            0,
        ),
        ('<testcase classname="x" name="y"/><testcase classname="x" name="y"/>', 2, 0, 0),
    ],
)
def test_junit_cannot_hide_missing_failed_skipped_or_duplicate_coverage(
    tmp_path, case, tests, skips, failures
):
    path = report(tmp_path, case, tests=tests, skips=skips, failures=failures)
    with pytest.raises(ValueError):
        validation.junit_summary(path, profile="fixture")


def test_only_named_windows_privilege_skip_is_allowed_in_unit_profile(tmp_path):
    cases = '<testcase classname="tests.unit.test_model_artifacts" name="passed"/><testcase classname="tests.unit.test_model_artifacts" name="test_symlink_component_rejected"><skipped message="Creating symlinks requires a Windows privilege."/></testcase>'
    path = report(tmp_path, cases, tests=2, skips=1)
    assert validation.junit_summary(path, profile="unit", host="nt")["passed"] == 1
    for profile, host in (("fixture", "nt"), ("real_bundle", "nt"), ("unit", "posix")):
        with pytest.raises(ValueError):
            validation.junit_summary(path, profile=profile, host=host)


def test_junit_rejects_entities_and_collection_errors(tmp_path):
    path = tmp_path / "bad.xml"
    for raw in (
        "<!DOCTYPE x><testsuites/>",
        "<testsuites/>",
        '<testsuites><testsuite tests="1"><error/></testsuite></testsuites>',
    ):
        path.write_text(raw)
        with pytest.raises(ValueError):
            validation.junit_summary(path, profile="unit")


@pytest.mark.parametrize(
    "profile,module",
    [
        ("real_bundle", "tests.unit.test_model_artifacts"),
        ("fixture", "tests.unit.test_model_artifacts"),
        ("unit", "tests.integration.test_snapshot_http"),
    ],
)
def test_junit_cannot_relabel_another_profile(tmp_path, profile, module):
    path = report(tmp_path, f'<testcase classname="{module}" name="ordinary_test"/>')
    with pytest.raises(ValueError, match="profile"):
        validation.junit_summary(path, profile=profile)


def test_junit_rejects_utf16_dtd_and_root_errors_and_unexecuted_case(tmp_path):
    path = report(tmp_path, '<testcase classname="x" name="ordinary_test"/>')
    xml = path.read_text()
    cases = [
        (
            '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE testsuites [<!ENTITY n "ordinary_test">]>'
            + xml.replace("ordinary_test", "&n;")
        ).encode("utf-16"),
        xml.replace("</testsuites>", '<error message="collection failure"/></testsuites>').encode(),
        xml.replace('name="ordinary_test"', 'name="ordinary_test" status="notrun"').encode(),
    ]
    for raw in cases:
        path.write_bytes(raw)
        with pytest.raises(ValueError):
            validation.junit_summary(path, profile="fixture")


def test_publication_preserves_existing_bytes_and_competing_writer(tmp_path):
    path = tmp_path / "receipt.json"

    def publish(number):
        try:
            release.publish(path, {"winner": number})
            return True
        except (ValueError, FileExistsError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, (1, 2)))
    assert sum(results) == 1
    original = path.read_bytes()
    assert validation.load_receipt(path)["winner"] in (1, 2)
    with pytest.raises(ValueError):
        release.publish(path, {"winner": 3})
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".integration-*"))


def test_publication_failure_leaves_no_empty_success_receipt(tmp_path, monkeypatch):
    def fail(*_):
        raise OSError("unavailable hard-link publication")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError):
        release.publish(tmp_path / "receipt.json", {"ok": True})
    assert not list(tmp_path.iterdir())


def test_quality_pin_and_completion_cannot_be_bypassed(tmp_path):
    data = validation.load_receipt(validation.QUALITY_PATH, checksum="payload_sha256")
    manifest = {"bundle_version": data["bundle_version"], "components": data["components"]}
    pin = data["identity"]["manifest_sha256"]
    validation.validate_quality(validation.QUALITY_PATH, validation.QUALITY_PIN, manifest, pin)
    with pytest.raises(ValueError):
        validation.validate_quality(validation.QUALITY_PATH, "0" * 64, manifest, pin)
    data["complete"] = False
    data.pop("payload_sha256")
    data["payload_sha256"] = digest(data)
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        validation.validate_quality(path, file_sha(path), manifest, pin)


@pytest.fixture
def http_evidence():
    # Reuse the public finite telemetry schema, with explicitly synthetic references.
    data = validation.load_receipt(
        validation.ROOT / "benchmarks/serving/hardening_boundary_validation_v1.json"
    )
    references = [
        {"user_id": f"u{i}", "trace": {"output": ["a"], "route": "hybrid_learned"}}
        for i in range(100)
    ]
    references.append({"user_id": None, "trace": {"output": ["a"], "route": "recent_popularity"}})
    manifest = {
        "bundle_version": data["identity"]["bundle_version"],
        "snapshot": {"cutoff": 100},
        "components": {"references.json": {"sha256": data["identity"]["references_sha256"]}},
    }
    data["identity"]["reader_runtime_code_sha256"] = runtime_code()
    data["identity"]["files_sha256"] = validation.http_identity()
    data["identity"]["request_sequence_sha256"] = digest([r["user_id"] for r in references])
    data["runtime"] = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": {
            n: importlib.metadata.version(n)
            for n in ("fastapi", "starlette", "uvicorn", "h11", "pydantic", "anyio", "psutil")
        },
    }
    output = digest(
        [
            {
                "items": ["a"],
                "route": r["trace"]["route"],
                "bundle_version": manifest["bundle_version"],
                "cutoff": 100,
            }
            for r in references
        ]
    )
    for phase in ("cache_off_anonymous", "cache_on_bearer"):
        data[phase]["reference_outputs_sha256"] = output
    return data, manifest, references


def test_http_evidence_checks_outputs_protocol_and_telemetry(http_evidence):
    data, manifest, refs = http_evidence
    assert validation.validate_http(
        data, manifest=manifest, pin=data["identity"]["manifest_sha256"], references=refs
    )["exact_http_parity"]


@pytest.mark.parametrize(
    "path,value",
    [
        (("identity", "files_sha256"), {}),
        (("parity", "warm_references"), 99),
        (("parity", "all_passed"), 1),
        (("schema_version",), True),
        (("cache_on_bearer", "reference_outputs_sha256"), "0" * 64),
        (("cache_off_anonymous", "protection_checks", "request_trailers_rejected"), False),
        (("cache_on_bearer", "telemetry", "deliveries"), 210),
        (("cache_off_anonymous", "memory", "observed_samples_within_target"), True),
        (("runtime", "packages", "uvicorn"), "foreign"),
        (("cache_on_bearer", "policy", "authentication"), "foreign"),
        (("cache_off_anonymous", "timing", "warm", "latency_samples"), 0),
        (("cache_off_anonymous", "timing", "cold", "latency_samples"), True),
        (("cache_on_bearer", "timing", "hit_warm", "latency_p95_ms"), -1),
        (("cache_on_bearer", "timing", "hit_warm", "latency_p95_ms"), float("inf")),
        (("cache_on_bearer", "timing", "hit_warm", "latency_p50_ms"), 1000000),
        (("cache_on_bearer", "timing", "hit_cold", "latency_avg_ms"), 0.1),
        (("cache_on_bearer", "startup_seconds"), 0),
        (("cache_on_bearer", "startup_seconds"), float("nan")),
        (("cache_on_bearer", "memory", "sampling_interval_seconds"), 1),
    ],
)
def test_http_rejects_tampered_or_incomplete_evidence(http_evidence, path, value):
    data, manifest, refs = http_evidence
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError):
        validation.validate_http(
            data, manifest=manifest, pin=data["identity"]["manifest_sha256"], references=refs
        )


def test_http_empty_timings_cannot_pass_ratio_gates(http_evidence):
    data, manifest, refs = http_evidence
    for phase in ("cache_off_anonymous", "cache_on_bearer"):
        for row in data[phase]["timing"].values():
            for field in row:
                row[field] = 0
    gates = validation.benefit_gates(
        data["cache_off_anonymous"]["timing"], data["cache_on_bearer"]["timing"]
    )
    assert all(gates.values())  # Ratios alone are insufficient measurement evidence.
    data["benefit_gates"] = {**gates, "all_passed": True}
    with pytest.raises(ValueError, match="sample"):
        validation.validate_http(
            data, manifest=manifest, pin=data["identity"]["manifest_sha256"], references=refs
        )


def test_loader_cannot_substitute_fit_or_partial_references():
    data = {
        "verification": "offline-bundle-loader-v1",
        "parity": True,
        "reference_requests": 101,
        "manifest_sha256": "pin",
        "bundle_version": "v",
        "loader_runtime_code_sha256": runtime_code(),
        "producer_runtime_code_sha256": "producer",
        "inference_code_sha256": inference_code(),
        "runtime": environment(),
        "quality_recomputed": False,
        "source_quality_receipt_sha256": "quality",
        "verifier_sha256_lf": file_sha(validation.ROOT / "scripts/verify_model_artifacts.py"),
    }
    kwargs = {
        "manifest": {"bundle_version": "v", "runtime_code_sha256": "producer"},
        "pin": "pin",
        "quality_pin": "quality",
    }
    validation.validate_loader(data, **kwargs)
    for field, value in (
        ("reference_requests", 1),
        ("quality_recomputed", True),
        ("inference_code_sha256", "foreign"),
    ):
        invalid = copy.deepcopy(data)
        invalid[field] = value
        with pytest.raises(ValueError):
            validation.validate_loader(invalid, **kwargs)


def test_command_timeout_reaps_its_child_process(tmp_path):
    pid_file = tmp_path / "child.pid"
    program = "import subprocess,sys,time,pathlib; child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        release.run_command(
            ["-c", program, str(pid_file)], log_path=tmp_path / "timeout.log", timeout=2
        )
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(0.05)
    assert not psutil.pid_exists(pid)


def test_gate_removes_external_test_filters_and_credentials(monkeypatch):
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "RECSYS_API_TOKEN"):
        monkeypatch.setenv(name, "private")
    env = release.command_environment()
    assert not {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH", "RECSYS_API_TOKEN"}.intersection(
        env
    )
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_gate_fingerprint_includes_transitive_fixture_producers_and_all_profiles():
    identity = validation.source_identity()
    for name in (
        "scripts/benchmark_candidates.py",
        "scripts/benchmark_diversity.py",
        "scripts/build_model_artifacts.py",
        "scripts/release_validation.py",
        "tests/conftest.py",
        "tests/integration/service_process.py",
        ".github/workflows/ci.yml",
        ".gitattributes",
    ):
        assert identity[name] == file_sha(validation.ROOT / name)
    assert not any(name.startswith((".local/", "artifacts/")) for name in identity)


@pytest.mark.parametrize("enabled", [False, True])
def test_real_profile_flags_cannot_silently_select_no_real_coverage(tmp_path, enabled):
    arguments = [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/test_release_verification.py",
        "--collect-only",
        "-q",
        "--bundle-path",
        str(tmp_path),
        "--bundle-manifest-sha256",
        "0" * 64,
    ]
    if enabled:
        arguments.append("--run-real-bundle")
    process = subprocess.run(
        arguments,
        cwd=validation.ROOT,
        env=release.command_environment(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode != 0
    expected = b"selected no real-bundle tests" if enabled else b"require --run-real-bundle"
    assert expected in process.stderr
