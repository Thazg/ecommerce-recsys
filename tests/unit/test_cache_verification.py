"""Prospective HTTP-cache gates and response lineage checks."""

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")

from scripts.verify_service_cache import benefit_gates, check_response  # noqa: E402


def test_benefit_thresholds_are_inclusive_and_independent():
    off = {"warm": {"latency_p95_ms": 100.0}}
    on = {"hit_warm": {"latency_p95_ms": 50.0}, "miss_warm": {"latency_p95_ms": 125.0}}
    assert benefit_gates(off, on) == {"hit_latency": True, "miss_latency": True}
    on["miss_warm"]["latency_p95_ms"] = 125.01
    assert benefit_gates(off, on) == {"hit_latency": True, "miss_latency": False}


def test_response_check_rejects_wrong_cache_path_lineage_or_output():
    row = {"trace": {"route": "hybrid_learned", "output": ["a"]}}
    manifest = {"bundle_version": "fixture", "snapshot": {"cutoff": 99}}
    response = {
        "request_id": "id",
        "items": ["a"],
        "route": "hybrid_learned",
        "bundle_version": "fixture",
        "cutoff": 99,
        "manifest_sha256": "a" * 64,
        "cache_status": "hit",
        "degraded": False,
        "degraded_reason": None,
    }
    check_response(response, row, manifest, "a" * 64, 20, "hit")
    for mutation in (
        {"manifest_sha256": "b" * 64},
        {"cache_status": "miss"},
        {"items": ["b"]},
        {"degraded": True},
    ):
        with pytest.raises(ValueError):
            check_response(response | mutation, row, manifest, "a" * 64, 20, "hit")
