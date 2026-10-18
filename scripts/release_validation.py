"""Fail-closed evidence checks for the functional snapshot integration gate."""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import platform
import re
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path

from ecommerce_recsys.artifacts.contract import (
    digest,
    environment,
    file_sha,
    inference_code,
    runtime_code,
)
from ecommerce_recsys.serving.security import SecuritySettings, authority

if __package__:
    from scripts.verify_service_cache import benefit_gates
    from scripts.verify_service_hardening import code_identity as http_identity
    from scripts.verify_service_observability import parse_metrics, value
else:
    from verify_service_cache import benefit_gates
    from verify_service_hardening import code_identity as http_identity
    from verify_service_observability import parse_metrics, value

ROOT = Path(__file__).resolve().parents[1]
QUALITY_PATH = ROOT / "benchmarks/artifacts/fold09_v1.json"
QUALITY_PIN = "12a954fb8535ff69ba767fde9b7c4c949f3aec421dbba995ba1a8137ad2098e8"
POLICY = {
    "verification": "snapshot-functional-integration-v1",
    "api_version": "1.2.0",
    "warm_references": 100,
    "cold_references": 1,
    "numerical_parity": "exact candidate order, evidence/features/scores digests and Top-K IDs; no tolerance",
    "http_parity": "exact ordered IDs, route, version, cutoff, manifest; fresh server request IDs",
    "deployment_eligible": False,
    "scope": "functional integration; no new quality, Linux bundle, load, recovery or resource-budget certification",
}


def source_identity():
    paths = {
        *[p.relative_to(ROOT).as_posix() for p in (ROOT / "src/ecommerce_recsys").rglob("*.py")],
        *[p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("*.py")],
        *[p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").rglob("*.py")],
        *[p.relative_to(ROOT).as_posix() for p in (ROOT / "requirements").glob("*.txt")],
        "pyproject.toml",
        ".gitattributes",
        ".github/workflows/ci.yml",
    }
    return {name: file_sha(ROOT / name) for name in sorted(paths)}


def unique_object(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("Duplicate evidence field.")
        result[key] = item
    return result


def load_receipt(path, *, checksum="content_sha256"):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("Evidence must be a bounded regular JSON file.")

    def invalid_constant(_):
        raise ValueError("Nonfinite evidence field.")

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
        if not isinstance(data, dict) or data.get(checksum) != digest(
            {k: v for k, v in data.items() if k != checksum}
        ):
            raise ValueError("Evidence digest differs.")
        return data
    except (UnicodeError, RecursionError, TypeError, OverflowError):
        raise ValueError("Evidence is not valid finite JSON.") from None


def evidence_check(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, OverflowError, ZeroDivisionError):
            raise ValueError("Evidence schema differs from the required contract.") from None

    return invoke


@evidence_check
def validate_quality(path, pin, manifest, manifest_pin):
    if not re.fullmatch("[0-9a-f]{64}", pin or "") or file_sha(Path(path)) != pin:
        raise ValueError("Trusted quality receipt pin differs.")
    data = load_receipt(path, checksum="payload_sha256")
    if (
        data.get("artifact") != "offline-model-bundle-validation-v1"
        or data.get("complete") is not True
        or data.get("loaded_quality_matches_policy") is not True
        or data.get("bundle_version") != manifest["bundle_version"]
        or data.get("identity", {}).get("manifest_sha256") != manifest_pin
        or data.get("components") != manifest["components"]
    ):
        raise ValueError("Quality evidence is incomplete or belongs to another snapshot.")
    return data


@evidence_check
def junit_summary(path, *, profile, host=os.name):
    """Count actual cases, not only an editable testsuite summary attribute."""
    if profile not in {"unit", "fixture", "real_bundle"}:
        raise ValueError("Unknown test profile.")
    path = Path(path)
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("JUnit report exceeds its budget.")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("JUnit must use UTF-8.") from None
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("JUnit declarations are not supported.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ValueError("Invalid JUnit XML.") from None
    suites = list(root) if root.tag == "testsuites" else [root]
    if root.tag not in {"testsuites", "testsuite"} or not suites:
        raise ValueError("Missing JUnit suites.")
    if any(suite.tag != "testsuite" for suite in suites):
        raise ValueError("Unexpected JUnit root outcome or container.")
    seen, passed, skipped = set(), 0, []
    for suite in suites:
        cases = suite.findall("testcase")
        if list(suite.findall("testsuite")):
            raise ValueError("Nested JUnit suites are unsupported.")
        if any(suite.find(tag) is not None for tag in ("error", "failure")):
            raise ValueError("JUnit collection failed.")
        if int(suite.get("tests", "-1")) != len(cases):
            raise ValueError("JUnit declared count differs from actual cases.")
        for case in cases:
            identity = case.get("classname", ""), case.get("name", "")
            if not all(identity) or identity in seen:
                raise ValueError("Missing or duplicate JUnit case identity.")
            module, name = identity
            real_module = "tests.integration.test_snapshot_references"
            belongs = {
                "unit": module.startswith("tests.unit."),
                "fixture": module.startswith("tests.integration.") and module != real_module,
                "real_bundle": module == real_module
                and name == "test_pinned_producer_numerics_in_an_isolated_loader",
            }[profile]
            if not belongs or "status" in case.attrib:
                raise ValueError("JUnit case does not belong to the executed profile.")
            seen.add(identity)
            if case.find("error") is not None or case.find("failure") is not None:
                raise ValueError("Required regression failed.")
            skip = case.find("skipped")
            if skip is None:
                passed += 1
            else:
                message = skip.get("message", "")
                windows_privilege = (
                    host == "nt"
                    and identity
                    == ("tests.unit.test_model_artifacts", "test_symlink_component_rejected")
                    and "Windows privilege" in message
                )
                optional_experiment = (
                    identity[0]
                    in {
                        "tests.unit.test_ann_feasibility",
                        "tests.unit.test_two_tower",
                        "test_ann_feasibility",
                        "test_two_tower",
                    }
                    and "could not import" in message
                    and any(s in message for s in ("'torch'", "'faiss'"))
                )
                if profile != "unit" or not (windows_privilege or optional_experiment):
                    raise ValueError("Required coverage was skipped.")
                skipped.append(
                    "windows_symlink_privilege"
                    if windows_privilege
                    else "optional_experiment_dependency"
                )
        actual_failures = sum(c.find("failure") is not None for c in cases)
        actual_errors = sum(c.find("error") is not None for c in cases)
        actual_skips = sum(c.find("skipped") is not None for c in cases)
        if any(
            int(suite.get(key, "-1")) != number
            for key, number in (
                ("failures", actual_failures),
                ("errors", actual_errors),
                ("skipped", actual_skips),
            )
        ):
            raise ValueError("JUnit outcome totals differ.")
    if not passed:
        raise ValueError("Required profile executed no successful cases.")
    return {
        "profile": profile,
        "tests": len(seen),
        "passed": passed,
        "skipped": len(skipped),
        "skip_reasons": skipped,
        "all_passed": True,
    }


@evidence_check
def validate_loader(data, *, manifest, pin, quality_pin, count=101):
    if (
        data.get("verification") != "offline-bundle-loader-v1"
        or data.get("parity") is not True
        or type(data.get("reference_requests")) is not int
        or data["reference_requests"] != count
        or data.get("manifest_sha256") != pin
        or data.get("bundle_version") != manifest["bundle_version"]
        or data.get("loader_runtime_code_sha256") != runtime_code()
        or data.get("producer_runtime_code_sha256") != manifest["runtime_code_sha256"]
        or data.get("inference_code_sha256") != inference_code()
        or data.get("runtime") != environment()
        or data.get("quality_recomputed") is not False
        or data.get("source_quality_receipt_sha256") != quality_pin
        or data.get("verifier_sha256_lf") != file_sha(ROOT / "scripts/verify_model_artifacts.py")
    ):
        raise ValueError("Loader evidence is stale, incomplete or belongs to another snapshot.")


def validate_http_timings(phase, *, enabled):
    expected = (
        {"miss_warm": 100, "miss_cold": 1, "hit_warm": 100, "hit_cold": 1}
        if enabled
        else {"warm": 100, "cold": 1}
    )
    timings = phase["timing"]
    if set(timings) != set(expected):
        raise ValueError("HTTP timing paths differ from the measured sample.")
    if (
        type(phase["startup_seconds"]) not in (int, float)
        or not math.isfinite(phase["startup_seconds"])
        or phase["startup_seconds"] <= 0
    ):
        raise ValueError("HTTP startup timing must be finite and positive.")
    for name, samples in expected.items():
        row = timings[name]
        fields = ("latency_avg_ms", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms")
        if (
            set(row) != {"latency_samples", *fields}
            or type(row["latency_samples"]) is not int
            or row["latency_samples"] != samples
        ):
            raise ValueError("HTTP latency sample count differs from the reference cohort.")
        values = [row[key] for key in fields]
        if (
            any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values)
            or values[1:] != sorted(values[1:])
            or (samples == 1 and len(set(values)) != 1)
        ):
            raise ValueError("HTTP latency summaries must be finite, positive and ordered.")


@evidence_check
def validate_http(data, *, manifest, pin, references):
    if (
        len(references) != 101
        or len({r["user_id"] for r in references}) != 101
        or sum(r["trace"]["route"] == "hybrid_learned" for r in references) != 100
        or sum(r["trace"]["route"] == "recent_popularity" for r in references) != 1
    ):
        raise ValueError("HTTP references must contain 100 warm and one cold contexts.")
    identity = data.get("identity", {})
    expected_parity = {
        "warm_references": 100,
        "cold_references": 1,
        "prefix_checks_per_phase": 6,
        "cold_reuse_checks_per_phase": 2,
        "post_denial_recovery_per_phase": 1,
        "all_passed": True,
    }
    runtime = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": {
            n: importlib.metadata.version(n)
            for n in ("fastapi", "starlette", "uvicorn", "h11", "pydantic", "anyio", "psutil")
        },
    }
    if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("api_version") != POLICY["api_version"]
        or data.get("runtime") != runtime
        or identity.get("manifest_sha256") != pin
        or identity.get("references_sha256") != manifest["components"]["references.json"]["sha256"]
        or identity.get("bundle_version") != manifest["bundle_version"]
        or identity.get("reader_runtime_code_sha256") != runtime_code()
        or identity.get("files_sha256") != http_identity()
        or identity.get("request_sequence_sha256") != digest([r["user_id"] for r in references])
        or data.get("parity") != expected_parity
        or any(type(data["parity"][k]) is not type(v) for k, v in expected_parity.items())
        or data.get("reference_pacing_seconds") != 0.26
    ):
        raise ValueError("HTTP evidence identity/protocol/reference coverage differs.")
    expected_digest = digest(
        [
            {
                "items": row["trace"]["output"][:20],
                "route": row["trace"]["route"],
                "bundle_version": manifest["bundle_version"],
                "cutoff": manifest["snapshot"]["cutoff"],
            }
            for row in references
        ]
    )
    for name, enabled in (("cache_off_anonymous", False), ("cache_on_bearer", True)):
        phase = data[name]
        validate_http_timings(phase, enabled=enabled)
        policy = phase["policy"]
        authorities = tuple(policy["authorities"])
        if len(authorities) != 2:
            raise ValueError("HTTP listener authorities differ.")
        host, port = authority(authorities[0])
        if host != "127.0.0.1" or authority(authorities[1]) != ("localhost", port):
            raise ValueError("HTTP listener is not the expected local authority.")
        expected_policy = SecuritySettings(
            authorities=authorities, token=b"x" * 32 if enabled else None
        ).public_policy()
        expected_policy["authorities"] = list(expected_policy["authorities"])
        if policy != expected_policy or phase["cache_enabled"] is not enabled:
            raise ValueError("Measured HTTP protection policy differs.")
        checks = phase["protection_checks"]
        if (
            any(
                checks.get(k) is not True
                for k in (
                    "host_origin_encoding_body_json",
                    "header_size",
                    "header_deadline",
                    "body_deadline",
                    "request_trailers_rejected",
                )
            )
            or checks.get("auth_operational_endpoints") is not enabled
        ):
            raise ValueError("Required HTTP protection checks are missing.")
        metrics = parse_metrics(phase["telemetry"]["metrics_text"])
        requests, deliveries, primary = (238, 211, 101) if enabled else (136, 111, 111)
        if (
            phase["final"]["state"] != "ready"
            or phase["final"]["primary_calls"] != primary
            or phase["telemetry"]["all_passed"] is not True
            or phase["telemetry"]["http_requests"] != requests
            or phase["telemetry"]["deliveries"] != deliveries
            or phase["telemetry"]["owned_json_records"] != requests + 1
            or value(metrics, "recsys_http_requests_total") != requests
            or value(metrics, "recsys_deliveries_total") != deliveries
            or value(metrics, "recsys_primary_calls_total") != primary
            or value(metrics, "recsys_observer_errors_total") != 0
            or value(metrics, "recsys_primary_in_flight") != 0
            or value(metrics, "recsys_transport_events_total", event="trailers_rejected") != 2
            or value(metrics, "recsys_transport_events_total", event="header_timeout") != 1
            or value(metrics, "recsys_transport_events_total", event="input_limit") != 1
            or value(metrics, "recsys_http_errors_total", code="body_timeout") != 1
            or len(metrics) != phase["telemetry"]["sample_series"]
            or type(checks.get("forwarded_burst_denials")) is not int
            or checks["forwarded_burst_denials"] < 1
            or value(metrics, "recsys_http_errors_total", code="rate_limited")
            != checks["forwarded_burst_denials"]
        ):
            raise ValueError("HTTP evidence counters or completion checks differ.")
        output = phase["reference_outputs_sha256"]
        if not re.fullmatch("[0-9a-f]{64}", output) or output != expected_digest:
            raise ValueError("HTTP paired outputs differ.")
        expected_digest = output
        memory = phase["memory"]
        samples = [
            memory[k]
            for k in ("ready_rss_bytes", "after_requests_rss_bytes", "sampled_peak_rss_bytes")
        ]
        if (
            any(type(v) is not int or v <= 0 for v in samples)
            or samples[2] < max(samples[:2])
            or memory["charter_target_bytes"] != 2 * 1024**3
            or memory["sampling_interval_seconds"] != 0.05
            or memory["observed_samples_within_target"] is not (samples[2] <= 2 * 1024**3)
        ):
            raise ValueError("Memory measurements or budget disclosure differ.")
    gates = benefit_gates(data["cache_off_anonymous"]["timing"], data["cache_on_bearer"]["timing"])
    if data.get("benefit_gates") != {**gates, "all_passed": all(gates.values())} or not all(
        gates.values()
    ):
        raise ValueError("Prospective cache smoke gates failed.")
    return {
        "reference_outputs_sha256": expected_digest,
        "exact_http_parity": True,
        "protection_and_telemetry": True,
        "cache_ratio_smoke": True,
    }
