"""Offered-load accounting, strict parity and resumable capacity evidence."""

import copy
import json
import math
import time
from collections import Counter
from types import SimpleNamespace

import pytest

from scripts import benchmark_http_capacity as host
from scripts import http_capacity_workload as work


@pytest.fixture
def references():
    return [
        {"user_id": f"u{i}", "trace": {"route": "hybrid_learned", "output": ["a", "b"]}}
        for i in range(100)
    ] + [{"user_id": None, "trace": {"route": "recent_popularity", "output": ["b", "c"]}}]


def test_schedule_mix_is_exact_and_visits_every_warm_reference(references):
    requests = work.sequence(references, 150)
    assert Counter(cohort for _, _, cohort in requests) == {"warm": 120, "cold": 30}
    assert Counter(k for _, k, _ in requests) == {20: 90, 10: 30, 5: 30}
    assert len({row["user_id"] for row, _, c in requests if c == "warm"}) == 100
    assert len({(c, k) for _, k, c in requests}) == 6
    assert requests == work.sequence(references, 150)


@pytest.mark.parametrize("count", [True, 0, -1, 1.0, 10001])
def test_schedule_requires_bounded_integral_request_count(references, count):
    with pytest.raises(ValueError):
        work.sequence(references, count)


def delivery(status=200, *, cohort="warm", cache="disabled", elapsed=0.1):
    return {
        "status": status,
        "cohort": cohort,
        "cache": cache,
        "k": 20,
        "http_seconds": elapsed,
        "total_seconds": elapsed + 0.001,
        "dispatch_seconds": 0.001,
    }


def test_fast_rejections_and_shedding_never_hide_slow_successes():
    rows = [delivery(elapsed=0.8)] * 100 + [delivery(429, elapsed=0.001)] * 50
    result = work.summarize(
        rows, offered=200, duration=150, elapsed=151, resources={"rss_max_bytes": 3 * 1024**3}
    )
    assert result["rejection_fraction"] == 0.5
    assert result["client_shed"] == 50
    assert result["latency"]["warm_success"]["http"]["latency_p95_ms"] == 800
    assert not result["targets_met"]
    assert not result["targets"]["rss"]
    assert not result["targets"]["warm_http_p95"]
    assert result["completed_rps"] == 150 / 151


def test_empty_success_slice_is_not_certified():
    result = work.summarize(
        [delivery(503)], offered=1, duration=1, elapsed=1.1, resources={"rss_max_bytes": 1}
    )
    assert not result["targets"]["enough_warm_successes"]
    assert not result["targets_met"]


@pytest.mark.parametrize(
    "change", ["items", "route", "manifest", "cutoff", "degraded", "id", "cache", "header"]
)
def test_response_parity_checks_actual_content_and_lineage(references, change):
    row = references[0]
    value = {
        "request_id": "a" * 32,
        "items": ["a"],
        "route": "hybrid_learned",
        "manifest_sha256": "b" * 64,
        "bundle_version": "v1",
        "cutoff": 100,
        "degraded": False,
        "degraded_reason": None,
        "cache_status": "disabled",
    }
    headers = {
        "x-request-id": "a" * 32,
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
    }
    manifest = {"bundle_version": "v1", "snapshot": {"cutoff": 100}}
    assert (
        work.validate_response(200, value, headers, row, 1, manifest, "b" * 64, False) == "disabled"
    )
    if change == "header":
        headers["cache-control"] = "public"
    else:
        key, other = {
            "items": ("items", ["b"]),
            "route": ("route", "recent_popularity"),
            "manifest": ("manifest_sha256", "c" * 64),
            "cutoff": ("cutoff", 100.0),
            "degraded": ("degraded", True),
            "id": ("request_id", "d" * 32),
            "cache": ("cache_status", "hit"),
        }[change]
        value[key] = other
    with pytest.raises(ValueError):
        work.validate_response(200, value, headers, row, 1, manifest, "b" * 64, False)


@pytest.mark.parametrize("rss", [True, 0, -1, 1.0, 2**64])
def test_resource_bytes_reject_bool_float_and_invalid_bounds(rss):
    with pytest.raises(ValueError):
        work.resource_summary([{"rss_bytes": rss, "elapsed_seconds": 0.1, "cpu_seconds": 0.0}])


def test_resource_sampling_requires_finite_increasing_times():
    with pytest.raises(ValueError):
        work.resource_summary([])
    for samples in (
        [{"rss_bytes": 1, "elapsed_seconds": math.nan, "cpu_seconds": 0.0}],
        [{"rss_bytes": 1, "elapsed_seconds": 0.1, "cpu_seconds": 0.0}] * 2,
    ):
        with pytest.raises(ValueError):
            work.resource_summary(samples)


def test_open_loop_sheds_without_serializing_into_a_hidden_queue():
    process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=1024), cpu_times=lambda: (0.0, 0.0)
    )

    def slow(value):
        time.sleep(0.12)
        return delivery()

    rows, samples, elapsed = work.open_loop(
        list(range(10)), 100, 1, slow, process=process, sample_seconds=0.01
    )
    assert len(rows) == 1 and rows[0]["index"] == 0
    assert elapsed < 1
    assert samples


def test_client_and_service_counts_must_reconcile():
    before = {
        key: 0
        for key in (
            "posts",
            "deliveries",
            "hits",
            "misses",
            "primary",
            "busy",
            "rate_limited",
            "observer_errors",
        )
    }
    after = {**before, "posts": 3, "deliveries": 1, "primary": 1, "busy": 1, "rate_limited": 1}
    rows = [delivery(), delivery(429), delivery(503)]
    assert work.reconcile(before, after, rows, False) == after
    after["primary"] += 1
    with pytest.raises(ValueError):
        work.reconcile(before, after, rows, False)


@pytest.mark.parametrize("text", ["broken", "recsys_ready NaN", 'x{a="1",a="2"} 1', "x 1\nx 2"])
def test_metrics_malformed_or_duplicate_samples_fail(text):
    with pytest.raises(ValueError):
        work.metric_snapshot(text)


def complete_cell():
    cell = work.CELLS[0]
    offered = work.POLICY["duration_seconds"] * cell["rate"]
    rows = [delivery(cohort="cold" if i % 5 == 4 else "warm") for i in range(offered)]
    for i, row in enumerate(rows):
        row["k"] = (20, 20, 20, 10, 5)[i % 5]
    summary = work.summarize(
        rows,
        offered=offered,
        duration=150,
        elapsed=150.01,
        resources={
            "rss_max_bytes": 1024,
            "samples": 3000,
            "ready_rss_bytes": 1024,
            "after_priming_rss_bytes": 1024,
            "after_workload_rss_bytes": 1024,
            "driver_rss_bytes": 1024,
            "first_sample_seconds": 0.001,
            "last_sample_seconds": 149.99,
            "largest_sample_gap_seconds": 0.06,
            "sampled_server_cpu_seconds": 1.0,
            "server_cpu_seconds": 1.0,
            "driver_cpu_seconds": 0.5,
        },
    )
    return {
        "cell": cell,
        "pre_references": 101,
        "post_references": 101,
        "parity_passed": True,
        "request_sequence_sha256": "a" * 64,
        "summary": summary,
        "offered_cohorts": {"warm": 120, "cold": 30},
        "offered_k": {"20": 90, "10": 30, "5": 30},
        "cgroup_memory_peak_bytes": 2048,
        "telemetry_delta": {
            "posts": offered,
            "deliveries": offered,
            "hits": 0,
            "misses": 0,
            "primary": offered,
            "busy": 0,
            "rate_limited": 0,
            "observer_errors": 0,
        },
        "cleanup": {
            "graceful": True,
            "cleanup_events": 1,
            "removed": True,
            "prior_already_exited_abnormally": False,
        },
    }


def test_partial_and_foreign_checkpoints_cannot_resume(tmp_path):
    identity = {"source": "a"}
    path = tmp_path / "checkpoint.json"
    row = complete_cell()
    assert host.verify_cell(row, work.CELLS[0]) is row
    host.release.atomic(path, {"identity": identity, "cells": [row]})
    assert len(host.load_progress(path, identity)["cells"]) == 1
    with pytest.raises(ValueError):
        host.load_progress(path, {"source": "b"})
    row["cleanup"]["graceful"] = False
    host.release.atomic(path, {"identity": identity, "cells": [row]})
    with pytest.raises(ValueError):
        host.load_progress(path, identity)


@pytest.mark.parametrize(
    "field,value", [("offered", True), ("attempted", 151), ("successes", 149), ("client_shed", 2)]
)
def test_checkpoint_counts_cannot_be_inconsistent(field, value):
    row = complete_cell()
    row["summary"][field] = value
    with pytest.raises(ValueError):
        host.verify_cell(row, work.CELLS[0])


def test_existing_receipt_cannot_be_overwritten(tmp_path):
    output = tmp_path / "result.json"
    output.write_text("preserved")
    with pytest.raises(ValueError, match="Preserve"):
        host.verify(tmp_path, "0" * 64, output, tmp_path / "work")
    assert output.read_text() == "preserved"


def test_cached_command_does_not_change_the_frozen_default(tmp_path):
    backend = host.CapacityBackend(tmp_path, tmp_path, "scope", True)
    assert backend.command[:4] == ["--bundle-path", "/model", "--port", "8000"]
    assert "--cache-max-entries" in backend.command
    assert "--busy-policy" not in backend.command
    plain = host.CapacityBackend(tmp_path, tmp_path, "scope", False)
    assert plain.command == ["--bundle-path", "/model", "--port", "8000"]


def test_unknown_profile_and_duplicate_cells_are_not_accepted(tmp_path):
    row = complete_cell()
    bad = copy.deepcopy(row)
    bad["cell"]["name"] = "unmeasured"
    with pytest.raises(ValueError):
        host.verify_cell(bad, work.CELLS[0])
    path = tmp_path / "checkpoint.json"
    host.release.atomic(path, {"identity": {}, "cells": [row, row]})
    with pytest.raises(ValueError):
        host.load_progress(path, {})
    assert json.loads(path.read_text())["cells"]


@pytest.mark.parametrize("events", [0, True, 2])
def test_real_cell_cannot_finish_with_invalid_cleanup_proof(tmp_path, monkeypatch, events):
    row = complete_cell()
    evidence = {"identity": {"image_id": "sha256:" + "a" * 64, "manifest_sha256": "b" * 64}}

    class FakeBackend:
        def __init__(self, *args):
            pass

        def create(self, *args):
            return "c" * 64

        def start(self, *args):
            pass

        def healthy(self, *args):
            return True

        def call(self, *args, **kwargs):
            return SimpleNamespace(stdout=json.dumps(row))

        def remove(self, *args, **kwargs):
            return {
                "removed": True,
                "graceful": True,
                "cleanup_events": events,
                "prior_already_exited_abnormally": False,
            }

    monkeypatch.setattr(host, "CapacityBackend", FakeBackend)
    with pytest.raises(ValueError, match="graceful cleanup"):
        host.run_cell(work.CELLS[0], tmp_path, evidence, tmp_path)
    assert (tmp_path / "owned.json").is_file()


@pytest.mark.parametrize("change", ["nan", "empty_samples", "false_gate", "wrong_fraction"])
def test_checkpoint_cannot_tamper_with_measurements_or_gates(change):
    row = complete_cell()
    if change == "nan":
        row["summary"]["latency"]["warm_success"]["http"]["latency_p95_ms"] = math.nan
    elif change == "empty_samples":
        row["summary"]["resources"]["samples"] = True
    elif change == "false_gate":
        row["summary"]["targets"]["rss"] = False
        row["summary"]["targets_met"] = False
    else:
        row["summary"]["rejection_fraction"] = 0.5
    with pytest.raises(ValueError):
        host.verify_cell(row, work.CELLS[0])


@pytest.mark.parametrize(
    "path,value",
    [
        (("telemetry_delta", "posts"), 0),
        (("telemetry_delta", "primary"), True),
        (("telemetry_delta", "observer_errors"), 1),
        (("summary", "duration_seconds"), 1),
        (("summary", "including_drain_seconds"), float("inf")),
        (("summary", "success_rps"), 999999),
        (("summary", "completed_rps"), True),
        (("summary", "offered_rps"), float("nan")),
        (("summary", "resources", "last_sample_seconds"), 1),
        (("summary", "resources", "first_sample_seconds"), 1),
        (("summary", "resources", "largest_sample_gap_seconds"), 100),
        (("summary", "resources", "samples"), 100),
        (("summary", "resources", "driver_rss_bytes"), True),
        (("summary", "resources", "driver_cpu_seconds"), float("nan")),
        (("summary", "resources", "sampled_server_cpu_seconds"), 2),
        (("summary", "cache_counts"), {"hit": 150}),
        (("summary", "cohort_attempts"), {"warm": 150}),
        (("summary", "k_attempts"), {"20": 150}),
        (("summary", "latency", "busy_rejected", "http", "latency_samples"), 1),
    ],
)
def test_rechecks_measurement_semantics_even_with_a_recomputed_checksum(tmp_path, path, value):
    row = complete_cell()
    parent = row
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValueError):
        host.verify_cell(row, work.CELLS[0])
    if type(value) is float and not math.isfinite(value):
        return  # The canonical JSON writer also refuses non-finite values.
    checkpoint = tmp_path / "checkpoint.json"
    host.release.atomic(checkpoint, {"identity": {}, "cells": [row]})
    with pytest.raises(ValueError):
        host.load_progress(checkpoint, {})


@pytest.mark.parametrize(
    "field,value",
    [("warm_fraction", 0.5), ("warm_fraction", True), ("k_mix", {"20": 1.0})],
)
def test_unsupported_policy_cannot_misdescribe_schedule_or_resume(
    references, tmp_path, monkeypatch, field, value
):
    monkeypatch.setitem(work.POLICY, field, value)
    with pytest.raises(ValueError, match="Unsupported traffic mix"):
        work.sequence(references, 150)
    with pytest.raises(ValueError, match="Unsupported traffic mix"):
        host.load_progress(tmp_path / "missing.json", {})


def test_original_measured_cells_pass_the_stricter_accounting():
    receipt = json.loads(
        (host.ROOT / "benchmarks/performance/http_capacity_validation_v1.json").read_text(
            encoding="utf-8"
        )
    )
    for row, cell in zip(receipt["cells"], work.CELLS, strict=True):
        assert host.verify_cell(row, cell) is row
