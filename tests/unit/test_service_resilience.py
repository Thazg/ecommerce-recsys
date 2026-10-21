"""Strict resilience evidence and event-controlled numerical failure ownership."""

import asyncio
import copy
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ecommerce_recsys.artifacts import Recommendation
from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.service import (
    Busy,
    InferenceFailed,
    NotReady,
    RecommendationService,
    State,
)
from scripts import http_capacity_workload as original
from scripts import service_resilience_workload as work
from scripts import verify_service_resilience as host


@pytest.fixture
def references():
    return [
        {"user_id": f"u{i}", "trace": {"route": "hybrid_learned", "output": ["a", "b"]}}
        for i in range(100)
    ] + [{"user_id": None, "trace": {"route": "recent_popularity", "output": ["b"]}}]


def complete_load(references, index=0):
    cell = work.CELLS[index]
    phases = []
    for phase in cell["phases"]:
        seconds = phase["seconds"]
        helper = work.capacity_helper(seconds)
        requests = helper.sequence(references, seconds * phase["rate"])
        rows = [
            {
                "status": 200,
                "cache": "disabled",
                "cohort": c,
                "k": k,
                "http_seconds": 0.1,
                "total_seconds": 0.101,
                "dispatch_seconds": 0.001,
            }
            for _, k, c in requests
        ]
        resources = {
            "rss_max_bytes": 1024,
            "ready_rss_bytes": 1024,
            "after_priming_rss_bytes": 1024,
            "after_workload_rss_bytes": 1024,
            "driver_rss_bytes": 1024,
            "samples": seconds * 20,
            "first_sample_seconds": 0.001,
            "last_sample_seconds": seconds - 0.01,
            "largest_sample_gap_seconds": 0.06,
            "sampled_server_cpu_seconds": 1.0,
            "server_cpu_seconds": 1.0,
            "driver_cpu_seconds": 0.5,
        }
        from collections import Counter

        n = len(rows)
        result = {
            "phase": phase,
            "request_sequence_sha256": work.sequence_identity(requests),
            "offered_cohorts": dict(Counter(c for _, _, c in requests)),
            "offered_k": dict(Counter(str(k) for _, k, _ in requests)),
            "summary": helper.summarize(
                rows, offered=n, duration=seconds, elapsed=seconds + 0.01, resources=resources
            ),
            "telemetry_delta": {
                "posts": n,
                "deliveries": n,
                "hits": 0,
                "misses": 0,
                "primary": n,
                "busy": 0,
                "rate_limited": 0,
                "observer_errors": 0,
            },
        }
        if phase["name"].startswith("quiet-"):
            result["recovery"] = {"references": 2, "seconds": 0.6, "ready_and_drained": True}
        phases.append(result)
    return {
        "step": cell["name"],
        "startup_seconds": 10,
        "driver_payload_sha256": host.digest(host.driver_source()),
        "cleanup": {
            "removed": True,
            "graceful": True,
            "cleanup_events": 1,
            "prior_already_exited_abnormally": False,
        },
        "result": {
            "cell": cell,
            "phases": phases,
            "pre_references": 101,
            "post_references": 101,
            "parity_passed": True,
            "cgroup_memory_peak_bytes": 1024**3,
            "pressure": {
                "allocated_bytes": cell["pressure_bytes"],
                "driver_rss_before_bytes": 1024,
                "driver_rss_occupied_bytes": 1024 + cell["pressure_bytes"],
            },
        },
    }


@pytest.mark.parametrize("index", [0, 1, 2])
def test_fixed_load_matrix_and_private_duration_helpers(references, index):
    old = copy.deepcopy(original.POLICY)
    row = complete_load(references, index)
    assert host.validate_result(row, row["step"], references) is row
    assert original.POLICY == old


@pytest.mark.parametrize(
    "path,value",
    [
        (("summary", "duration_seconds"), 1),
        (("summary", "success_rps"), 999),
        (("summary", "successes"), True),
        (("summary", "transport_error_fraction"), False),
        (("telemetry_delta", "posts"), 0),
        (("telemetry_delta", "primary"), True),
        (("summary", "resources", "samples"), 10),
        (("summary", "resources", "first_sample_seconds"), 1),
        (("summary", "resources", "last_sample_seconds"), 1),
        (("summary", "resources", "largest_sample_gap_seconds"), 100),
        (("summary", "resources", "driver_cpu_seconds"), math.nan),
        (("summary", "latency", "warm_success", "http", "latency_samples"), 1),
        (("offered_k",), {"20": 600}),
        (("request_sequence_sha256",), "0" * 64),
    ],
)
def test_window_rejects_inconsistent_measurements(references, path, value):
    row = complete_load(references)["result"]["phases"][0]
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        work.validate_window(row, work.CELLS[0]["phases"][0], references)


@pytest.mark.parametrize("change", ["phase", "recovery", "pressure", "cleanup", "payload"])
def test_resigned_partial_or_foreign_checkpoints_cannot_resume(tmp_path, references, change):
    row = complete_load(references)
    if change == "phase":
        row["result"]["phases"] = []
    elif change == "recovery":
        row = complete_load(references, 1)
        row["result"]["phases"][1]["recovery"]["seconds"] = 11
        with pytest.raises(ValueError):
            host.validate_result(row, row["step"], references)
        return
    elif change == "pressure":
        row["result"]["pressure"]["allocated_bytes"] = False
    elif change == "cleanup":
        row["cleanup"]["cleanup_events"] = True
    else:
        row["driver_payload_sha256"] = "0" * 64
    path = tmp_path / "checkpoint.json"
    host.release.atomic(path, {"identity": {}, "steps": [row]})
    with pytest.raises(ValueError):
        host.load_progress(path, {}, references)


def test_checkpoint_foreign_identity_and_duplicate_steps_fail(tmp_path, references):
    path = tmp_path / "checkpoint.json"
    row = complete_load(references)
    host.release.atomic(path, {"identity": {}, "steps": [row]})
    assert len(host.load_progress(path, {}, references)["steps"]) == 1
    with pytest.raises(ValueError):
        host.load_progress(path, {"foreign": True}, references)
    host.release.atomic(path, {"identity": {}, "steps": [row, row]})
    with pytest.raises(ValueError):
        host.load_progress(path, {}, references)


@pytest.mark.parametrize(
    "field,value", [("warm_fraction", 0.5), ("seed", 0), ("k_mix", {"20": 1.0}), ("targets", {})]
)
def test_unsupported_metadata_cannot_change_declared_schedule(monkeypatch, field, value):
    monkeypatch.setitem(work.POLICY, field, value)
    with pytest.raises(ValueError):
        work.capacity_helper()


def test_driver_payload_compiles_and_completed_receipts_are_nonoverwriting(tmp_path):
    compile(host.driver_source(), "<driver>", "exec")
    path = tmp_path / "completed.json"
    path.write_text("preserved", encoding="utf-8")
    with pytest.raises(ValueError, match="Preserve"):
        host.verify(tmp_path, "0" * 64, path, tmp_path)
    assert path.read_text(encoding="utf-8") == "preserved"


def test_missing_explicit_test_evidence_is_an_error():
    with pytest.raises(ValueError, match="Explicit full"):
        host.test_evidence(None, None, None)


@pytest.mark.parametrize("value", [10**400, -(10**400), True, None, "150", math.nan, math.inf])
def test_bounded_rejects_invalid_and_huge_numbers_without_overflow(value):
    assert host.bounded(value, 150, positive=True) is False


@pytest.mark.parametrize("value,expected", [(0, False), (0.5, True), (150, True), (151, False)])
def test_bounded_preserves_positive_boundary(value, expected):
    assert host.bounded(value, 150, positive=True) is expected


def write_profile(path, cases):
    suite = ET.Element("testsuite", tests=str(len(cases)), failures="0", errors="0", skipped="0")
    for module, name in cases:
        ET.SubElement(suite, "testcase", classname=module, name=name)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


@pytest.mark.parametrize("change", ["missing", "extra", "same-count", "duplicate", "linux"])
def test_full_evidence_rejects_partial_or_substituted_profiles(tmp_path, monkeypatch, change):
    expected = {
        "unit": frozenset(
            {
                ("tests.unit.test_service_resilience", "test_example[a]"),
                ("tests.unit.test_service_resilience", "test_example[b]"),
                ("tests.unit.test_http_capacity", "test_upstream"),
            }
        ),
        "fixture": frozenset({("tests.integration.test_resilience_process", "test_fitted[0]")}),
    }
    paths = [tmp_path / name for name in ("unit.xml", "fixture.xml", "linux.json")]
    for path, profile in zip(paths[:2], expected, strict=True):
        write_profile(path, sorted(expected[profile]))
    monkeypatch.setattr(host, "collected_cases", lambda profile, source: expected[profile])
    linux = {
        "functional_passed": True,
        "owned_container_cleanup_verified": True,
        "identity": {
            "files_lf_sha256": host.release.code_identity(),
            "ci_inputs_sha256": {
                name: host.file_sha(host.ROOT / name)
                for name in {*host.FILES, *(name for name, _ in host.collection_sources())}
            },
        },
        "profiles": {
            p: {"all_passed": True, "passed": len(cases), "tests": len(cases), "skipped": 0}
            for p, cases in expected.items()
        },
    }
    host.release.atomic(paths[2], linux)
    assert host.test_evidence(*paths)["collected_cases_sha256"] == {
        p: host.digest(sorted(cases)) for p, cases in expected.items()
    }
    cases = sorted(expected["unit"])
    if change == "missing":
        cases = cases[:-1]
    elif change == "extra":
        cases.append(("tests.unit.test_service_resilience", "test_foreign"))
    elif change == "same-count":
        cases[-1] = (cases[-1][0], "test_example[unexecuted]")
    elif change == "duplicate":
        cases.append(cases[-1])
    else:
        linux["profiles"]["unit"]["passed"] -= 1
        host.release.atomic(paths[2], linux)
    write_profile(paths[0], cases)
    with pytest.raises(ValueError):
        host.test_evidence(*paths)


def test_collection_uses_actual_pytest_parameter_identities():
    source = host.collection_sources()
    cases = host.collected_cases("unit", source)
    assert (
        "tests.unit.test_service_resilience",
        "test_full_evidence_rejects_partial_or_substituted_profiles[same-count]",
    ) in cases
    assert any(module == "tests.unit.test_http_capacity" for module, _ in cases)


@pytest.mark.parametrize("field,value", [("warm_references", 0), ("outputs_sha256", "0" * 64)])
def test_recovery_checks_full_http_evidence_and_semantic_faults(references, field, value):
    qualified = json.loads(host.capacity.QUALIFICATION.read_text(encoding="utf-8"))
    # Generated release receipts are deliberately absent from fixture CI.
    child = {
        "operational_passed": True,
        "external_recovery_storage": True,
        "owned_containers_remaining": 0,
        "identity": {
            "files_lf_sha256": host.release.code_identity(),
            "qualification_sha256": host.capacity.QUALIFICATION_PIN,
            "manifest_sha256": qualified["identity"]["manifest_sha256"],
            "image_id": qualified["identity"]["image_id"],
        },
        "final_graceful_stop_verified": True,
        "rollback_restored_after_active_process_kill": True,
        "postcommit_journal_recovery_passed": True,
        "rejected_descriptor_preserved_active": True,
        "compound_recovery_preserved_former_active": True,
        "rejected_observer_preserved_active": True,
        "rejected_qualification_preserved_active": True,
        "invalid_descriptor_rejection": {
            k: True
            for k in (
                "valid_content_checksum",
                "active_pointer_unchanged",
                "owned_names_unchanged",
                "no_pending_journal",
                "active_healthy",
            )
        },
        "initial": {"http": copy.deepcopy(qualified["http"])},
        "replacement": {"http": copy.deepcopy(qualified["http"])},
        "rollback": {"http": copy.deepcopy(qualified["http"])},
        "stop": {
            "cleanup": {
                "removed": True,
                "graceful": True,
                "cleanup_events": 1,
                "prior_already_exited_abnormally": False,
            }
        },
    }
    child["content_sha256"] = host.digest(child)
    row = {
        "step": "release-recovery",
        "exercise_seconds": 300,
        "receipt": child,
        "receipt_payload_sha256": host.digest(child),
        "receipt_file_sha256": "a" * 64,
    }
    assert host.validate_result(row, row["step"], references) is row
    child["initial"]["http"][field] = value
    child["content_sha256"] = host.digest({k: v for k, v in child.items() if k != "content_sha256"})
    row["receipt_payload_sha256"] = host.digest(child)
    with pytest.raises(ValueError):
        host.validate_result(row, row["step"], references)


@pytest.mark.parametrize("change", ["scope", "id", "source", "writable", "network", "pin", "token"])
def test_controlled_fault_never_weakens_container_ownership(tmp_path, monkeypatch, change):
    backend = host.StartupBackend(tmp_path, tmp_path / "model", "scope", "corrupt")
    descriptor = {
        "release_id": "startup-corrupt",
        "image_id": "sha256:" + "a" * 64,
        "manifest_sha256": "b" * 64,
    }
    entry = {"container_name": "owned", "container_id": "c" * 64}
    mounts = [
        {"Type": "bind", "Target": "/model", "Source": str(backend.bundle), "ReadOnly": True},
        {
            "Type": "bind",
            "Target": "/model/weights.npy",
            "Source": str(backend.corrupt.resolve()),
            "ReadOnly": True,
        },
    ]
    state = {
        "Name": "/owned",
        "Id": entry["container_id"],
        "Image": descriptor["image_id"],
        "Config": {
            "User": "10001:10001",
            "Cmd": backend.command,
            "Entrypoint": ["python", "-m", "ecommerce_recsys.serving"],
            "Env": ["RECSYS_MANIFEST_SHA256=" + "b" * 64],
            "Labels": {"recsys.release.scope": "scope", "recsys.release.id": "startup-corrupt"},
        },
        "HostConfig": {
            "Mounts": mounts,
            "NetworkMode": "none",
            "PortBindings": None,
            "PublishAllPorts": False,
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "PidsLimit": 64,
            "Memory": host.linux.MEMORY,
            "MemorySwap": host.linux.MEMORY,
            "NanoCpus": 2_000_000_000,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16777216,mode=1777"},
        },
        "Mounts": [{"Type": "bind", "Destination": m["Target"], "RW": False} for m in mounts],
    }
    monkeypatch.setattr(host.linux, "inspect", lambda *a: state)
    assert backend.owned(entry, descriptor) is state
    if change == "scope":
        state["Config"]["Labels"]["recsys.release.scope"] = "foreign"
    elif change == "id":
        state["Id"] = "d" * 64
    elif change == "source":
        state["HostConfig"]["Mounts"][0]["Source"] = str(tmp_path / "foreign")
    elif change == "writable":
        state["Mounts"][0]["RW"] = True
    elif change == "network":
        state["HostConfig"]["NetworkMode"] = "bridge"
    elif change == "pin":
        state["Config"]["Env"] = ["RECSYS_MANIFEST_SHA256=" + "0" * 64]
    else:
        state["Config"]["Env"].append("RECSYS_API_TOKEN=unexpected")
    with pytest.raises(ValueError):
        backend.owned(entry, descriptor)


@pytest.mark.parametrize("kind", ["bad-pin", "missing", "corrupt"])
def test_startup_failure_requires_nonzero_nonoom_neverhealthy(kind, references):
    row = {
        "step": "startup-" + kind,
        "startup_seconds": 1,
        "cleanup": {
            "removed": True,
            "graceful": False,
            "cleanup_events": 0,
            "prior_already_exited_abnormally": False,
        },
        "failure": {
            "kind": kind,
            "exit_code": 1,
            "oom_killed": False,
            "ever_healthy": False,
            "exit_seconds": 1,
        },
    }
    assert host.validate_result(row, row["step"], references) is row
    for key, value in (
        ("exit_code", 0),
        ("oom_killed", True),
        ("ever_healthy", True),
        ("exit_seconds", 100),
    ):
        bad = copy.deepcopy(row)
        bad["failure"][key] = value
        with pytest.raises(ValueError):
            host.validate_result(bad, bad["step"], references)


class ControlledSnapshot:
    def __init__(self):
        self.manifest = {"bundle_version": "fixture-v1", "snapshot": {"cutoff": 99}}
        self.items, self.user_index = ("a", "b", "seen"), {"known": 0}
        self.entered, self.release = Event(), Event()
        self.release.set()
        self.blocking = self.fail = False
        self.active = 0

    def context(self, user_id):
        return SimpleNamespace(history=("seen",) if user_id == "known" else ())

    def recommend(self, user_id=None, *, k=20):
        self.active += 1
        try:
            if self.blocking:
                self.entered.set()
                if not self.release.wait(30):
                    raise TimeoutError("Controlled worker release missing.")
            if self.fail:
                raise ValueError("Controlled model dependency failure.")
            return Recommendation(
                ("a", "b")[:k],
                "hybrid_learned" if user_id == "known" else "recent_popularity",
                "fixture-v1",
                99,
            )
        finally:
            self.active -= 1


def service_for(model):
    return RecommendationService(
        ServiceSettings(Path("unused"), "a" * 64), loader=lambda *a, **k: model
    )


def test_cancelled_waiter_does_not_release_worker_and_owned_stop_waits():
    async def scenario():
        model = ControlledSnapshot()
        service = service_for(model)
        await service.start()
        model.blocking = True
        model.release.clear()
        pending = asyncio.create_task(service.recommend("known", 20, "a" * 32))
        try:
            assert await asyncio.to_thread(model.entered.wait, 10)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            with pytest.raises(Busy):
                await service.recommend("known", 20, "b" * 32)
            stopped = asyncio.create_task(service.stop())
            await asyncio.sleep(0)
            assert not stopped.done() and model.active == 1
        finally:
            model.release.set()
            await asyncio.wait_for(service.stop(), 10)
        await stopped
        assert service.state == State.STOPPED and model.active == 0 and service.bundle is None
        fresh = service_for(ControlledSnapshot())
        await fresh.start()
        await fresh.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["model", "executor"])
def test_primary_dependency_failure_invalidates_readiness_without_fallback(monkeypatch, failure):
    async def scenario():
        model = ControlledSnapshot()
        service = service_for(model)
        await service.start()
        if failure == "model":
            model.fail = True
        else:

            def rejected(*args, **kwargs):
                raise RuntimeError("Controlled executor dependency failure.")

            monkeypatch.setattr(service.executor, "submit", rejected)
        try:
            with pytest.raises(InferenceFailed):
                await service.recommend("known", 20, "a" * 32)
            assert service.state == State.FAILED and not service.readiness()[1]
            assert service.fallback_calls == 0
            with pytest.raises(NotReady):
                await service.recommend(None, 20, "b" * 32)
        finally:
            await service.stop()
        fresh = service_for(ControlledSnapshot())
        await fresh.start()
        await fresh.stop()

    asyncio.run(scenario())
