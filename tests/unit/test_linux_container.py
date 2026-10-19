"""Cross-platform tolerance cannot weaken output, lineage or isolation gates."""

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from containers import healthcheck, qualification
from ecommerce_recsys.artifacts.contract import digest, file_sha, write_json
from scripts import verify_linux_container as gate


def test_numeric_policy_accepts_small_platform_error_but_never_broadcasts():
    reference = np.array([[1.0, 0.0]])
    assert qualification.compare_arrays(reference + 1e-15, reference)["passed"]
    assert not qualification.compare_arrays(reference + 1e-8, reference)["passed"]
    for invalid in (reference[0], reference.astype("float32"), reference * np.nan):
        with pytest.raises(ValueError, match="shape/dtype/finiteness"):
            qualification.compare_arrays(invalid, reference)


@pytest.mark.parametrize("field", qualification.POLICY["exact_fields"])
def test_numeric_tolerance_never_applies_to_exact_fields(field):
    trace = {"pool": ["a", "b"], "output": ["a"], "evidence_sha256": "x", "route": "warm"}
    altered = copy.deepcopy(trace)
    altered[field] = "different"
    assert qualification.exact_differences(altered, trace) == [field]


def test_capture_preserves_hash_and_restores_hook_on_failure():
    original = qualification.runtime.array_digest
    array = np.array([1.0])

    class Bundle:
        def trace(self, user):
            first = qualification.runtime.array_digest(array)
            second = qualification.runtime.array_digest(array)
            if user == "fail":
                raise ValueError("trace failure")
            return (first, second)

    result, observed = qualification.capture(Bundle(), "ok")
    assert result == (original(array), original(array))
    assert len(observed) == 2 and observed[0] is not array
    with pytest.raises(ValueError, match="trace failure"):
        qualification.capture(Bundle(), "fail")
    assert qualification.runtime.array_digest is original


@pytest.mark.parametrize(
    "text",
    [
        "",
        "numpy>=2",
        "numpy==2 --hash=sha256:bad",
        "x==1 --hash=sha256:" + "a" * 64 + "\nx==2 --hash=sha256:" + "b" * 64,
    ],
)
def test_lock_rejects_unpinned_duplicate_or_unhashed_inputs(tmp_path, text):
    path = tmp_path / "runtime.lock"
    path.write_text(text)
    with pytest.raises(ValueError):
        gate.locked_packages(path)


def test_original_reference_archive_rejects_wrong_pin_model_and_inventory(tmp_path):
    archive = tmp_path / "numerics.npz"
    np.savez_compressed(archive, wrong=np.array([1.0]))
    data = {
        "schema_version": 1,
        "manifest_sha256": "m",
        "references_sha256": "r",
        "references": 101,
        "exact_producer_parity": True,
        "runtime_code_sha256": qualification.runtime_code(),
        "inference_code_sha256": qualification.inference_code(),
        "archive_sha256": file_sha(archive),
    }
    path = tmp_path / "metadata.json"
    write_json(path, {**data, "payload_sha256": digest(data)})
    for pin, manifest, error in (
        ("bad", "m", "metadata"),
        (file_sha(path), "foreign", "original model"),
        (file_sha(path), "m", "inventory"),
    ):
        with pytest.raises(ValueError, match=error):
            qualification.open_reference(tmp_path, pin, manifest, "r")


def safe_container():
    return {
        "Image": "sha256:image",
        "Config": {"User": "10001:10001"},
        "Mounts": [{"Destination": "/model", "RW": False, "Type": "bind"}],
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "ReadonlyRootfs": True,
            "PidsLimit": 64,
            "Memory": gate.MEMORY,
            "MemorySwap": gate.MEMORY,
            "NanoCpus": 2_000_000_000,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16777216,mode=1777"},
        },
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("NetworkMode", "bridge"),
        ("Privileged", True),
        ("CapDrop", []),
        ("SecurityOpt", []),
        ("ReadonlyRootfs", False),
        ("PidsLimit", 0),
        ("Memory", 0),
        ("MemorySwap", -1),
        ("NanoCpus", 0),
        ("PortBindings", {"8000/tcp": [{}]}),
    ],
)
def test_container_gate_rejects_unsafe_policy(field, value):
    state = safe_container()
    assert gate.validate_container(state, "sha256:image")["network"] == "none"
    state["HostConfig"][field] = value
    with pytest.raises(ValueError, match="resource policy"):
        gate.validate_container(state, "sha256:image")


def test_container_gate_rejects_root_writable_model_and_extra_mount():
    for change in (
        lambda s: s["Config"].update(User="root"),
        lambda s: s["Mounts"][0].update(RW=True),
        lambda s: s["Mounts"].append({"Destination": "/socket", "RW": False, "Type": "bind"}),
    ):
        state = safe_container()
        change(state)
        with pytest.raises(ValueError):
            gate.validate_container(state, "sha256:image")


def valid_evidence():
    model = {
        "manifest_sha256": "m",
        "references_sha256": "r",
        "policy": qualification.POLICY,
        "references": 101,
        "warm_references": 100,
        "cold_references": 1,
        "qualification_passed": True,
        "rss_after_references_bytes": 2_400_000_000,
        "mismatches": [],
        "bitwise_parity": True,
        "bitwise_mismatches": [],
        "array_errors": {
            k: {"max_abs_error": 0.0, "max_error_over_allowed": 0.0} for k in ("features", "scores")
        },
    }
    http = {
        "warm_references": 100,
        "cold_references": 1,
        "prefix_checks": 6,
        "unknown_cold_checks": 1,
        "denial_checks": 4,
        "recovery_checks": 1,
        "primary_calls": 109,
        "request_ids": 115,
        "exact_outputs": True,
        "pacing_seconds": 0.26,
        "cache_enabled": False,
        "busy_policy": "reject",
        "all_passed": True,
        "serving_rss_before_requests_bytes": 2_400_000_000,
        "serving_rss_after_requests_bytes": 2_410_000_000,
        "cgroup_memory_peak_bytes": 2_550_000_000,
        "warm_client_timing": {
            "latency_samples": 100,
            "latency_avg_ms": 1.0,
            "latency_p50_ms": 1.0,
            "latency_p95_ms": 2.0,
            "latency_p99_ms": 3.0,
        },
    }
    return model, http


@pytest.mark.parametrize("case", ["missing_arrays", "bound", "nan", "count", "zero", "bitwise_lie"])
def test_incomplete_or_invalid_evidence_cannot_pass(case):
    model, http = valid_evidence()
    gate.validate_evidence(model, http, "m", "r")
    if case == "missing_arrays":
        model["array_errors"] = {}
    elif case == "bound":
        model["array_errors"]["features"]["max_error_over_allowed"] = 1.1
    elif case == "nan":
        model["array_errors"]["scores"]["max_abs_error"] = float("nan")
    elif case == "count":
        http["warm_references"] = 99
    elif case == "zero":
        http["warm_client_timing"]["latency_p50_ms"] = 0
    else:
        model["bitwise_mismatches"] = [{"reference_index": 0, "fields": ["scores_sha256"]}]
    with pytest.raises(ValueError):
        gate.validate_evidence(model, http, "m", "r")


def test_failed_create_removes_only_its_owned_name(monkeypatch, tmp_path):
    calls = []

    def command(args, *unused, **kwargs):
        calls.append(args)
        if args[:2] == ["container", "create"]:
            raise ValueError("timed out after creation")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(gate, "docker", command)
    with pytest.raises(ValueError, match="timed out"):
        gate.create("image", tmp_path, "m", tmp_path)
    assert calls[1] == ["container", "rm", "--force", calls[0][3]]
    assert calls[0][3].startswith("recsys-qualification-")


def test_fresh_checkout_creates_private_scratch_parent(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert not (tmp_path / ".local").exists()
    first, second = gate.scratch_directory(), gate.scratch_directory()
    assert first.is_dir() and second.is_dir() and first != second
    assert first.parent == second.parent == tmp_path / ".local"


@pytest.mark.parametrize(
    "rm_code,present,ls_code", [(1, "owned-name\n", 0), (0, "owned-name\n", 0), (0, "", 1)]
)
def test_cleanup_must_confirm_absence(monkeypatch, tmp_path, rm_code, present, ls_code):
    responses = iter(
        [
            SimpleNamespace(stdout="", stderr="rm error", returncode=rm_code),
            SimpleNamespace(stdout=present, stderr="ls error", returncode=ls_code),
        ]
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **kw: next(responses))
    with pytest.raises(ValueError):
        gate.remove("owned-name", tmp_path)


@pytest.mark.parametrize("rm_code", [0, 1])
def test_cleanup_accepts_confirmed_absence_even_if_already_removed(monkeypatch, tmp_path, rm_code):
    responses = iter(
        [
            SimpleNamespace(stdout="", stderr="already absent", returncode=rm_code),
            SimpleNamespace(stdout="", stderr="", returncode=0),
        ]
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **kw: next(responses))
    gate.remove("owned-name", tmp_path)


def test_successful_job_cannot_hide_cleanup_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "create", lambda *a, **kw: "owned-name")
    monkeypatch.setattr(gate, "inspect", lambda *a: safe_container())

    def command(args, *unused, **kwargs):
        output = {"wait": "0", "logs": '{"fixture":true}', "ls": "owned-name"}.get(args[1], "")
        return SimpleNamespace(stdout=output, returncode=1 if args[1] == "rm" else 0)

    monkeypatch.setattr(gate, "docker", command)
    with pytest.raises(ValueError, match="remains after cleanup"):
        gate.job("sha256:image", tmp_path, "m", tmp_path, "runtime")


@pytest.mark.parametrize(
    "field",
    [
        "rss_after_references_bytes",
        "serving_rss_before_requests_bytes",
        "serving_rss_after_requests_bytes",
        "cgroup_memory_peak_bytes",
    ],
)
@pytest.mark.parametrize(
    "value", [-1, 0, True, 1.0, np.int64(1), float("nan"), float("inf"), "10", None, 10**1000]
)
def test_invalid_memory_measurements_are_rejected(field, value):
    model, http = valid_evidence()
    (model if field in model else http)[field] = value
    with pytest.raises(ValueError, match="Memory measurements"):
        gate.validate_evidence(model, http, "m", "r")


def test_context_cannot_be_shadowed_by_dockerfile_override(monkeypatch, tmp_path):
    (tmp_path / ".dockerignore").write_bytes((gate.ROOT / ".dockerignore").read_bytes())
    (tmp_path / "containers").mkdir()
    (tmp_path / "containers/Dockerfile.dockerignore").write_text("!**\n")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="overrides"):
        gate.validate_context()


def test_successful_build_with_empty_context_export_cannot_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "docker", lambda *a, **kw: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match="canaries"):
        gate.verify_context(tmp_path)


def test_context_allowlist_cannot_admit_private_data(monkeypatch, tmp_path):
    gate.validate_context()
    content = (gate.ROOT / ".dockerignore").read_text()
    (tmp_path / ".dockerignore").write_text(content + "\n!data/**\n")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="allowlist"):
        gate.validate_context()


def test_image_contract_rejects_root_and_published_port():
    config = {
        "User": "10001:10001",
        "Entrypoint": ["python", "-m", "ecommerce_recsys.serving"],
        "Cmd": ["--bundle-path", "/model", "--port", "8000"],
        "StopSignal": "SIGTERM",
        "Healthcheck": {
            "Test": ["CMD", "python", "/opt/runtime/healthcheck.py"],
            "Interval": 10_000_000_000,
            "Timeout": 5_000_000_000,
            "StartPeriod": 90_000_000_000,
            "Retries": 3,
        },
        "Env": [
            k + "=1"
            for k in (
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "PYTHONDONTWRITEBYTECODE",
            )
        ],
    }
    image = {"Id": "image", "Os": "linux", "Architecture": "amd64", "Config": config}
    assert gate.validate_image(image) == "image"
    for changes in (
        {"User": "root"},
        {"ExposedPorts": {"8000/tcp": {}}},
        {"StopSignal": "SIGKILL"},
    ):
        bad = copy.deepcopy(image)
        bad["Config"].update(changes)
        with pytest.raises(ValueError, match="Image architecture"):
            gate.validate_image(bad)


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"state": "ready", "status": "ready"}, True),
        (503, {}, False),
        (200, {"state": "failed", "status": "ready"}, False),
        (200, "x" * 20000, False),
    ],
)
def test_readiness_is_bounded_and_uses_auth_without_printing(
    monkeypatch, capsys, status, payload, expected
):
    calls = []
    monkeypatch.setattr(
        healthcheck.SecuritySettings,
        "from_environment",
        lambda **kwargs: SimpleNamespace(token=b"private-token"),
    )

    class Connection:
        def __init__(self, *args, **kwargs):
            assert kwargs["timeout"] == 3

        def request(self, *args, **kwargs):
            calls.append(kwargs)

        def getresponse(self):
            return SimpleNamespace(
                status=status, read=lambda limit: json.dumps(payload).encode()[:limit]
            )

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(healthcheck.http.client, "HTTPConnection", Connection)
    assert healthcheck.ready() is expected
    assert calls[0]["headers"] == {"Authorization": "Bearer private-token"}
    assert calls[-1] == "closed"
    assert "private-token" not in capsys.readouterr().out
