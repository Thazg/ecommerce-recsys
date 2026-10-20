"""Local release transactions, provenance and process-owned failure recovery."""

import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ecommerce_recsys.artifacts.contract import digest, file_sha, write_json
from scripts import snapshot_release as release
from scripts import verify_release_workflow as verification


class Backend:
    def __init__(self):
        self.containers = {}
        self.fail_verify = False
        self.fail_remove = False
        self.fail_create = False

    def image(self, descriptor):
        assert descriptor["image_id"].startswith("sha256:")

    def create(self, entry, descriptor):
        name = entry["container_name"]
        self.containers[name] = False
        if self.fail_create:
            raise ValueError("create failed after allocation")
        return digest(name)

    def start(self, entry, descriptor):
        self.containers[entry["container_name"]] = True

    def healthy(self, entry, descriptor):
        return self.containers.get(entry["container_name"], False)

    def owned_names(self):
        return list(self.containers)

    def verify(self, entry, descriptor, evidence):
        if self.fail_verify:
            raise ValueError("readiness observer fault")
        return {"fixture_verified": True}

    def remove(self, entry, descriptor, *, graceful):
        if self.fail_remove:
            raise ValueError("cleanup fault")
        self.containers.pop(entry["container_name"], None)
        return {"removed": True, "graceful": graceful, "cleanup_events": int(graceful)}


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    q = json.loads(
        (
            release.ROOT / "benchmarks/containers/linux_snapshot_boundary_validation_v1.json"
        ).read_text()
    )
    expected = copy.deepcopy(q["identity"]["files_sha256"])
    monkeypatch.setattr(release.linux, "sources", lambda: expected)
    monkeypatch.setattr(release.linux, "validate_runtime", lambda *args: None)
    monkeypatch.setattr(
        release,
        "verify_inventory",
        lambda *args: {
            "bundle_version": "retailrocket-fold09-v1",
            "components": {"references.json": {"sha256": q["identity"]["references_sha256"]}},
        },
    )
    monkeypatch.setattr(release, "code_identity", lambda: {"fixture": "fixed"})
    q.pop("content_sha256")
    path = tmp_path / "qualification.json"
    write_json(path, {**q, "content_sha256": digest(q)})
    backend = Backend()
    store = release.ReleaseStore(tmp_path / "store", tmp_path / "bundle", backend)
    store.stage("reference-a", path, file_sha(path))
    store.stage("reference-b", path, file_sha(path))
    return store, backend, path, q


@pytest.mark.parametrize("name", ["", "../escape", "A", "a/b", "a\\b", ".", "x" * 65, None, True])
def test_release_ids_cannot_escape_store(name):
    with pytest.raises(ValueError):
        release.release_id(name)


def test_stage_is_immutable_and_keeps_model_identity(prepared):
    store, _, path, _ = prepared
    target = store.root / "releases/reference-a.json"
    before = target.read_bytes()
    with pytest.raises(ValueError, match="Preserve"):
        store.stage("reference-a", path, file_sha(path))
    assert target.read_bytes() == before
    a, _ = store.descriptor("reference-a")
    b, _ = store.descriptor("reference-b")
    assert a["image_id"] == b["image_id"]
    assert a["manifest_sha256"] == b["manifest_sha256"]


def test_activate_replace_rollback_and_stop(prepared):
    store, backend, _, _ = prepared
    a = store.change("reference-a")
    old_name = a["state"]["active"]["container_name"]
    b = store.change("reference-b")
    assert old_name not in backend.containers
    assert b["state"]["generation"] == 2
    back = store.change(rollback=True)
    assert back["state"]["active"]["release_id"] == "reference-a"
    assert back["state"]["active"]["container_name"] != old_name
    assert len(backend.containers) == 1
    assert store.change(stop=True)["state"]["active"] is None
    assert not backend.containers and not (store.root / "pending.json").exists()


@pytest.mark.parametrize("fault", ["fail_verify", "fail_create"])
def test_candidate_fault_preserves_prior_pointer_and_removes_candidate(prepared, fault):
    store, backend, _, _ = prepared
    store.change("reference-a")
    before = (store.root / "active.json").read_bytes()
    setattr(backend, fault, True)
    with pytest.raises(ValueError):
        store.change("reference-b")
    assert (store.root / "active.json").read_bytes() == before
    assert len(backend.containers) == 1
    assert not (store.root / "pending.json").exists()


def test_postcommit_cleanup_failure_keeps_journal_and_recovers(prepared):
    store, backend, _, _ = prepared
    store.change("reference-a")
    backend.fail_remove = True
    with pytest.raises(ValueError, match="cleanup"):
        store.change("reference-b")
    assert store.state()["active"]["release_id"] == "reference-b"
    assert len(backend.containers) == 2
    with pytest.raises(ValueError, match="recovery"):
        store.change("reference-a")
    backend.fail_remove = False
    recovered = store.recover()
    assert recovered["committed"] is True
    assert len(backend.containers) == 1
    assert not (store.root / "pending.json").exists()


@pytest.mark.parametrize("candidate_fails", [False, True])
def test_explicit_rollback_can_restore_an_unhealthy_active(prepared, candidate_fails):
    store, backend, _, _ = prepared
    store.change("reference-a")
    prior = store.change("reference-b")["state"]
    name = prior["active"]["container_name"]
    backend.containers[name] = False
    backend.fail_verify = candidate_fails
    if candidate_fails:
        with pytest.raises(ValueError, match="observer"):
            store.change(rollback=True)
        assert store.state() == prior
        assert set(backend.containers) == {name}
        assert not (store.root / "pending.json").exists()
    else:
        restored = store.change(rollback=True)["state"]
        assert restored["active"]["release_id"] == "reference-a"
        assert name not in backend.containers
        assert len(backend.containers) == 1


@pytest.mark.parametrize("was_running", [False, True])
def test_retirement_distinguishes_prior_crash_from_failed_graceful_stop(
    tmp_path, monkeypatch, was_running
):
    backend = release.DockerBackend(tmp_path, tmp_path, "scope")
    monkeypatch.setattr(backend, "exists", lambda name: not removed)
    states = iter(
        [
            {"State": {"Running": was_running}},
            {"State": {"Running": False, "OOMKilled": False, "ExitCode": 1}},
        ]
    )
    monkeypatch.setattr(backend, "owned", lambda *a: next(states))
    monkeypatch.setattr(backend, "call", lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))
    removed = False

    def remove(*a):
        nonlocal removed
        removed = True

    monkeypatch.setattr(release.linux, "remove", remove)
    if was_running:
        with pytest.raises(ValueError, match="gracefully"):
            backend.remove({"container_name": "owned"}, {}, graceful=True)
        assert not removed
    else:
        result = backend.remove({"container_name": "owned"}, {}, graceful=True)
        assert result == {
            "removed": True,
            "graceful": False,
            "prior_already_exited_abnormally": True,
            "cleanup_events": 0,
        }


def test_stop_does_not_require_a_healthy_active_release(prepared):
    store, backend, _, _ = prepared
    state = store.change("reference-a")["state"]
    backend.containers[state["active"]["container_name"]] = False
    assert store.change(stop=True)["state"]["active"] is None
    assert not backend.containers


def test_readiness_loss_after_probe_preserves_prior_pointer(prepared, monkeypatch):
    store, backend, _, _ = prepared
    store.change("reference-a")
    before = (store.root / "active.json").read_bytes()

    def lost(entry, *args):
        backend.containers[entry["container_name"]] = False
        return {"fixture_verified": True}

    monkeypatch.setattr(backend, "verify", lost)
    with pytest.raises(ValueError, match="lost readiness"):
        store.change("reference-b")
    assert (store.root / "active.json").read_bytes() == before
    assert len(backend.containers) == 1


def test_uncommitted_cleanup_failure_recovers_to_original(prepared):
    store, backend, _, _ = prepared
    original = store.change("reference-a")["state"]
    backend.fail_verify = backend.fail_remove = True
    with pytest.raises(ValueError):
        store.change("reference-b")
    assert store.state() == original
    backend.fail_verify = backend.fail_remove = False
    assert store.recover()["committed"] is False
    assert store.state() == original and len(backend.containers) == 1


def test_pointer_commit_before_journal_phase_is_recoverable(prepared, monkeypatch):
    store, backend, _, _ = prepared
    store.change("reference-a")
    original = release.atomic

    def interrupt(path, data):
        if path.name == "pending.json" and data.get("phase") == "committed":
            raise ValueError("crash after pointer commit")
        original(path, data)

    monkeypatch.setattr(release, "atomic", interrupt)
    with pytest.raises(ValueError, match="crash"):
        store.change("reference-b")
    monkeypatch.setattr(release, "atomic", original)
    assert store.recover()["committed"] is True
    assert store.state()["active"]["release_id"] == "reference-b"
    assert len(backend.containers) == 1


def test_inconsistent_journal_cannot_remove_current_active(prepared):
    store, backend, _, _ = prepared
    prior = store.change("reference-a")["state"]
    target = {
        **prior,
        "generation": prior["generation"] + 1,
        "previous": {k: prior["active"][k] for k in ("release_id", "descriptor_sha256")},
    }
    release.atomic(
        store.root / "pending.json",
        {
            "schema_version": release.STATE_VERSION,
            "scope": store.scope,
            "prior": prior,
            "target": target,
            "candidate": prior["active"],
            "phase": "verified",
        },
    )
    with pytest.raises(ValueError, match="Inconsistent"):
        store.recover()
    assert store.state() == prior and len(backend.containers) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("channel", "production"),
        ("controller_sha256", "0" * 64),
        ("image_id", "latest"),
        ("manifest_sha256", "0" * 64),
    ],
)
def test_descriptor_tampering_is_rejected_even_with_new_checksum(prepared, field, value):
    store, _, _, _ = prepared
    path = store.root / "releases/reference-a.json"
    data = json.loads(path.read_text())
    data.pop("content_sha256")
    data[field] = value
    release.atomic(path, data)
    with pytest.raises(ValueError):
        store.descriptor("reference-a")


@pytest.mark.parametrize(
    "field,value",
    [
        ("qualification_passed", False),
        ("deployment_eligible", True),
        ("container_cleanup_verified", False),
        ("build_context", {}),
        ("negative_startup", {}),
        ("graceful_cleanup_events", 0),
        ("graceful_cleanup_events", True),
        ("graceful_cleanup_events", 1.0),
        ("negative_startup", {"bad_pin": 1, "missing": True, "corrupt": True}),
        ("negative_startup", []),
    ],
)
def test_incomplete_upstream_cannot_be_staged(prepared, field, value):
    store, _, path, q = prepared
    q[field] = value
    release.atomic(path, q)
    with pytest.raises(ValueError):
        store.stage("foreign", path, file_sha(path))
    assert not (store.root / "releases/foreign.json").exists()


def test_changed_source_and_wrong_pin_are_rejected(prepared, monkeypatch):
    store, _, path, _ = prepared
    with pytest.raises(ValueError, match="pin"):
        store.stage("bad-pin", path, "0" * 64)
    monkeypatch.setattr(release.linux, "sources", lambda: {"changed": "source"})
    with pytest.raises(ValueError, match="stale"):
        store.stage("bad-source", path, file_sha(path))


def test_generation_bounds_and_no_previous(prepared):
    store, _, _, _ = prepared
    with pytest.raises(ValueError, match="previous"):
        store.change(rollback=True)
    state = store.state()
    state["generation"] = 2**63 - 1
    release.atomic(store.root / "active.json", state)
    with pytest.raises(ValueError, match="generation"):
        store.change("reference-a")
    state["generation"] = True
    release.atomic(store.root / "active.json", state)
    with pytest.raises(ValueError, match="state"):
        store.state()


def test_cross_process_lock_is_nonblocking_and_releases(tmp_path):
    code = "from pathlib import Path; from scripts.snapshot_release import operation_lock\nwith operation_lock(Path(__import__('sys').argv[1])): pass"
    with release.operation_lock(tmp_path):
        process = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            cwd=release.ROOT,
            capture_output=True,
            timeout=30,
        )
        assert process.returncode != 0 and b"Another release" in process.stderr
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=release.ROOT,
        capture_output=True,
        timeout=30,
    )
    assert process.returncode == 0


def test_lock_is_released_when_owner_process_is_killed(tmp_path):
    marker = tmp_path / "owner-ready"
    code = "from pathlib import Path; import sys,time; from scripts.snapshot_release import operation_lock\np=Path(sys.argv[1])\nwith operation_lock(p):\n (p/'owner-ready').write_text('ready'); time.sleep(120)"
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=release.ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not marker.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        with pytest.raises(ValueError, match="Another release"):
            with release.operation_lock(tmp_path):
                pass
    finally:
        process.kill()
        process.wait(timeout=30)
    with release.operation_lock(tmp_path):
        pass


def test_failed_atomic_pointer_write_preserves_old_state(prepared, monkeypatch):
    store, backend, _, _ = prepared
    store.change("reference-a")
    before = (store.root / "active.json").read_bytes()
    replace = release.os.replace

    def fail(source, target):
        if Path(target).name == "active.json":
            raise OSError("pointer failure")
        replace(source, target)

    monkeypatch.setattr(release.os, "replace", fail)
    with pytest.raises(OSError, match="pointer failure"):
        store.change("reference-b")
    assert (store.root / "active.json").read_bytes() == before
    assert len(backend.containers) == 1
    assert not (store.root / "pending.json").exists()


def test_ambiguous_recovery_does_not_choose_a_pointer(prepared):
    store, backend, _, _ = prepared
    store.change("reference-a")
    backend.fail_remove = True
    with pytest.raises(ValueError):
        store.change("reference-b")
    state = store.state()
    state["generation"] += 2
    release.atomic(store.root / "active.json", state)
    backend.fail_remove = False
    with pytest.raises(ValueError, match="either journal"):
        store.recover()
    assert len(backend.containers) == 2 and (store.root / "pending.json").exists()


def compound_failure(prepared):
    store, backend, _, _ = prepared
    initial = store.change("reference-a")["state"]
    backend.fail_remove = True
    with pytest.raises(ValueError, match="cleanup"):
        store.change("reference-b")
    backend.fail_remove = False
    backend.containers[store.state()["active"]["container_name"]] = False
    return store, backend, initial


@pytest.mark.parametrize("operation", ["rollback", "stop"])
def test_compound_failure_retains_old_instance_then_unblocks_operation(prepared, operation):
    store, backend, initial = compound_failure(prepared)
    recovered = store.recover()
    assert recovered["retirement_deferred"] is True
    assert recovered["state"]["retained"] == [initial["active"]]
    assert backend.containers[initial["active"]["container_name"]] is True
    assert len(backend.containers) == 2 and not (store.root / "pending.json").exists()
    result = store.change(**{operation: True})
    assert result["state"]["retained"] == []
    assert initial["active"]["container_name"] not in backend.containers
    assert len(result["cleanup"]["retained_cleanup"]) == 1
    assert len(backend.containers) == (1 if operation == "rollback" else 0)


def test_failed_rollback_after_deferral_keeps_old_instance_and_ownership(prepared):
    store, backend, initial = compound_failure(prepared)
    before = store.recover()["state"]
    backend.fail_verify = True
    with pytest.raises(ValueError, match="observer"):
        store.change(rollback=True)
    assert store.state() == before
    assert backend.containers[initial["active"]["container_name"]] is True
    assert len(backend.containers) == 2


def test_deferred_pointer_before_journal_unlink_is_recoverable(prepared, monkeypatch):
    store, backend, initial = compound_failure(prepared)
    unlink = Path.unlink

    def fail(path, *a, **k):
        if path == store.root / "pending.json":
            raise OSError("interrupted journal removal")
        return unlink(path, *a, **k)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(OSError, match="interrupted"):
        store.recover()
    state = store.state()
    monkeypatch.setattr(Path, "unlink", unlink)
    assert store.recover()["state"] == state
    assert state["retained"] == [initial["active"]]
    assert len(backend.containers) == 2


def test_retained_cleanup_failure_is_resumable_after_new_verified_commit(prepared, monkeypatch):
    store, backend, initial = compound_failure(prepared)
    store.recover()
    remove = backend.remove

    def fail(entry, *a, **k):
        if entry["container_name"] == initial["active"]["container_name"]:
            raise ValueError("retained removal failed")
        return remove(entry, *a, **k)

    monkeypatch.setattr(backend, "remove", fail)
    with pytest.raises(ValueError, match="retained removal"):
        store.change(rollback=True)
    assert store.state()["active"]["release_id"] == "reference-a"
    assert (store.root / "pending.json").exists()
    monkeypatch.setattr(backend, "remove", remove)
    assert store.recover()["committed"] is True
    assert len(backend.containers) == 1


@pytest.mark.parametrize("change", ["duplicate", "foreign_name", "too_many", "null"])
def test_invalid_retained_inventory_is_rejected(prepared, change):
    store, _, initial = compound_failure(prepared)
    state = store.recover()["state"]
    if change == "duplicate":
        state["retained"].append(state["active"])
    elif change == "foreign_name":
        state["retained"][0]["container_name"] = "foreign"
    elif change == "too_many":
        state["retained"] = [initial["active"]] * (release.MAX_RETAINED + 1)
    else:
        state["retained"] = [None]
    with pytest.raises(ValueError):
        store.validate_state(state)


@pytest.mark.parametrize(
    "change", ["graceful", "events", "bool_events", "abnormal", "removed", "missing"]
)
def test_final_stop_cannot_publish_success_without_proven_drain(change):
    cleanup = {
        "removed": True,
        "graceful": True,
        "cleanup_events": 1,
        "prior_already_exited_abnormally": False,
    }
    verification.require_graceful_stop({"cleanup": cleanup})
    if change == "missing":
        cleanup = None
    else:
        key, value = {
            "graceful": ("graceful", False),
            "events": ("cleanup_events", 0),
            "bool_events": ("cleanup_events", True),
            "abnormal": ("prior_already_exited_abnormally", True),
            "removed": ("removed", False),
        }[change]
        cleanup[key] = value
    with pytest.raises(ValueError, match="graceful"):
        verification.require_graceful_stop({"cleanup": cleanup})


def test_external_recovery_root_rejects_checkout_and_relative_paths(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(verification, "ROOT", checkout)
    for path in (checkout, checkout / ".local", Path("relative")):
        with pytest.raises(ValueError, match="external|outside"):
            verification.external_work_root(path)
    external = tmp_path / "operations"
    assert verification.external_work_root(external) == external.resolve()


@pytest.mark.parametrize("pending", [True, False])
def test_prior_attempt_must_be_recovered_before_new_ci_qualification(tmp_path, pending):
    store = tmp_path / "github-1-1/release-qualification-example/release-store"
    store.mkdir(parents=True)
    if pending:
        (store / "pending.json").write_text("{}")
    else:
        release.atomic(store / "active.json", {"active": {"owned": True}, "retained": []})
    with pytest.raises(ValueError, match="Prior qualification"):
        verification.require_idle_work_root(tmp_path)


def test_external_store_survives_checkout_removal(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    external = verification.external_work_root(tmp_path / "external")
    journal = external / "pending.json"
    journal.write_text("preserve me")
    (checkout / ".local").mkdir()
    (checkout / ".local/temp").write_text("disposable")
    target = checkout.resolve()
    assert target.parent == tmp_path.resolve() and target.name == "checkout"
    shutil.rmtree(target)  # Only the verified temporary fixture, never the real checkout.
    assert not checkout.exists()
    assert journal.read_text() == "preserve me"


def test_failed_deferred_pointer_write_keeps_journal_and_prior_instances(prepared, monkeypatch):
    store, backend, _ = compound_failure(prepared)
    before = (store.root / "active.json").read_bytes()
    replace = release.os.replace

    def fail(source, target):
        if Path(target).name == "active.json":
            raise OSError("deferred pointer failed")
        replace(source, target)

    monkeypatch.setattr(release.os, "replace", fail)
    with pytest.raises(OSError, match="deferred pointer"):
        store.recover()
    assert (store.root / "active.json").read_bytes() == before
    assert (store.root / "pending.json").exists() and len(backend.containers) == 2
    monkeypatch.setattr(release.os, "replace", replace)
    assert store.recover()["retirement_deferred"] is True


def test_abnormal_final_drain_prevents_success_receipt(prepared, monkeypatch, tmp_path):
    _, _, evidence_path, _ = prepared

    class FaultBackend(Backend):
        fail_readiness = False
        fail_retirement = False

        def __init__(self, *args):
            super().__init__()
            self.verified = {}

        def verify(self, entry, descriptor, evidence):
            if self.fail_readiness:
                self.fail_readiness = False
                raise ValueError("controlled readiness observer fault")
            self.verified[entry["container_name"]] = evidence["http"]
            return evidence["http"]

        def owned(self, entry, descriptor):
            running = self.containers[entry["container_name"]]
            return {"State": {"Running": running, "ExitCode": 0 if running else 137}}

        def call(self, args, **kwargs):
            assert args[:3] == ["kill", "--signal", "KILL"]
            self.containers[args[-1]] = False

        def owned_names(self):
            return list(self.containers)

        def remove(self, entry, descriptor, *, graceful):
            if graceful and self.fail_retirement:
                self.fail_retirement = False
                raise ValueError("controlled retirement observer fault")
            running = self.containers.pop(entry["container_name"], False)
            final_stop = len(self.verified) == 3 and entry["container_name"] == next(
                reversed(self.verified)
            )
            return {
                "removed": True,
                "graceful": bool(graceful and running and not final_stop),
                "prior_already_exited_abnormally": not running or final_stop,
                "cleanup_events": int(graceful and running and not final_stop),
            }

    monkeypatch.setattr(verification, "ObservedBackend", FaultBackend)
    output = tmp_path / "must-not-publish.json"
    with pytest.raises(ValueError, match="Final owned stop"):
        verification.verify(
            tmp_path / "bundle",
            evidence_path,
            file_sha(evidence_path),
            output,
            work_root=tmp_path / "external",
        )
    assert not output.exists()


def test_missing_target_is_unhealthy_without_inspecting_an_absent_object(tmp_path, monkeypatch):
    backend = release.DockerBackend(tmp_path, tmp_path, "scope")
    monkeypatch.setattr(backend, "exists", lambda name: False)
    monkeypatch.setattr(backend, "owned", lambda *a: pytest.fail("Absent object was inspected"))
    assert backend.healthy({"container_name": "missing"}, {}) is False


def test_missing_target_with_pending_journal_can_defer_and_roll_back(prepared):
    store, backend, initial = compound_failure(prepared)
    backend.containers.pop(store.state()["active"]["container_name"])
    assert store.recover()["state"]["retained"] == [initial["active"]]
    assert store.change(rollback=True)["state"]["active"]["release_id"] == "reference-a"
    assert len(backend.containers) == 1


def test_journal_cannot_alias_a_retained_instance_as_new_candidate(prepared):
    store, backend, initial = compound_failure(prepared)
    prior = store.recover()["state"]
    candidate = initial["active"]
    target = {
        **prior,
        "generation": prior["generation"] + 1,
        "active": candidate,
        "retained": [],
        "previous": {k: prior["active"][k] for k in ("release_id", "descriptor_sha256")},
    }
    release.atomic(
        store.root / "pending.json",
        {
            "schema_version": release.STATE_VERSION,
            "scope": store.scope,
            "prior": prior,
            "target": target,
            "candidate": candidate,
            "phase": "verified",
        },
    )
    with pytest.raises(ValueError, match="Inconsistent"):
        store.recover()
    assert backend.containers[candidate["container_name"]] is True
    assert len(backend.containers) == 2


def test_invalid_descriptor_rejection_proves_no_activation_side_effects(prepared):
    store, backend, _, _ = prepared
    store.change("reference-a")
    # The verification helper uses its own two immutable exercise IDs.
    path = store.root / "releases/reference-b.json"
    data = release.load_receipt(path)
    data.pop("content_sha256")
    data["release_id"] = "local-reference-b"
    release.publish(store.root / "releases/local-reference-b.json", data)
    before = (store.root / "active.json").read_bytes()
    descriptor = path.read_bytes()
    witness = verification.reject_invalid_descriptor(store, backend)
    assert witness["reason"] == "descriptor_identity_mismatch"
    assert witness["valid_content_checksum"] is True
    assert witness["active_pointer_unchanged"] and witness["owned_names_unchanged"]
    assert (store.root / "active.json").read_bytes() == before
    assert path.read_bytes() == descriptor and len(backend.containers) == 1
    invalid = release.load_receipt(store.root / "releases/invalid-descriptor.json")
    assert invalid["manifest_sha256"] == "0" * 64


def test_release_verifier_requires_external_root_in_cli(tmp_path):
    process = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release_workflow.py",
            "--bundle",
            str(tmp_path),
            "--qualification",
            str(tmp_path / "qualification.json"),
            "--qualification-sha256",
            "0" * 64,
            "--output",
            str(tmp_path / "must-not-exist.json"),
        ],
        cwd=release.ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 2 and "--work-root" in process.stderr
    assert not (tmp_path / "must-not-exist.json").exists()
