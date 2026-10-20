"""Exercise real isolated release/rollback with one qualified image and model."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ecommerce_recsys.artifacts.contract import file_sha

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import check_release_workflows as workflows  # noqa: E402
from scripts import snapshot_release as release  # noqa: E402
from scripts import verify_linux_container as linux  # noqa: E402
from scripts.verify_release import publish  # noqa: E402


class ObservedBackend(release.DockerBackend):
    """Controlled observer faults, never an operator bypass or model-math patch."""

    fail_readiness = False
    fail_retirement = False

    def __init__(self, *args):
        super().__init__(*args)
        self.verified = {}

    def verify(self, entry, descriptor, evidence):
        if self.fail_readiness:
            self.fail_readiness = False
            self.owned(entry, descriptor)
            raise ValueError("controlled readiness observer fault")
        result = super().verify(entry, descriptor, evidence)
        self.verified[entry["container_name"]] = result
        return result

    def remove(self, entry, descriptor, *, graceful):
        if graceful and self.fail_retirement:
            self.fail_retirement = False
            raise ValueError("controlled retirement observer fault")
        return super().remove(entry, descriptor, graceful=graceful)

    def owned_names(self):
        response = self.call(
            [
                "ls",
                "--all",
                "--filter",
                "label=recsys.release.scope=" + self.scope,
                "--format",
                "{{.Names}}",
            ]
        )
        return response.stdout.splitlines()


def external_work_root(path):
    supplied = Path(path)
    if not supplied.is_absolute():
        raise ValueError("Qualification work root must be absolute and external.")
    resolved = supplied.resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("Qualification work root must be outside the checkout.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def require_idle_work_root(path):
    root = external_work_root(path)
    for store in root.glob("github-*/release-qualification-*/release-store"):
        if (store / "pending.json").exists() or (store / "pending.json").is_symlink():
            raise ValueError("Prior qualification requires explicit recovery.")
        active = store / "active.json"
        if active.exists() or active.is_symlink():
            state = release.load_receipt(active)
            if state.get("active") is not None or state.get("retained"):
                raise ValueError("Prior qualification still owns model instances.")
    return root


def require_graceful_stop(result):
    cleanup = result.get("cleanup")
    if (
        not isinstance(cleanup, dict)
        or cleanup.get("removed") is not True
        or cleanup.get("graceful") is not True
        or type(cleanup.get("cleanup_events")) is not int
        or cleanup["cleanup_events"] != 1
        or cleanup.get("prior_already_exited_abnormally") is not False
    ):
        raise ValueError("Final owned stop did not prove graceful cleanup.")


def reject_invalid_descriptor(store, backend):
    """Reject semantic scratch metadata without changing a valid bundle or descriptor."""
    before = (store.root / "active.json").read_bytes()
    names = sorted(backend.owned_names())
    valid, _ = store.descriptor("local-reference-b")
    invalid = {k: v for k, v in valid.items() if k != "content_sha256"}
    invalid.update(release_id="invalid-descriptor", manifest_sha256="0" * 64)
    path = store.root / "releases/invalid-descriptor.json"
    publish(path, invalid)
    try:
        store.change("invalid-descriptor")
    except ValueError as error:
        if str(error) != "Descriptor image/model differs from qualified identity.":
            raise
    else:
        raise ValueError("Invalid descriptor activation was accepted.")
    active = store.state()["active"]
    if (
        before != (store.root / "active.json").read_bytes()
        or names != sorted(backend.owned_names())
        or (store.root / "pending.json").exists()
        or active is None
        or not backend.healthy(active, store.entry_descriptor(active))
    ):
        raise ValueError("Invalid descriptor rejection changed the active release.")
    return {
        "descriptor_sha256": file_sha(path),
        "invalid_field": "manifest_sha256",
        "reason": "descriptor_identity_mismatch",
        "valid_content_checksum": True,
        "active_pointer_unchanged": True,
        "owned_names_unchanged": True,
        "no_pending_journal": True,
        "active_healthy": True,
    }


def verify(bundle, path, pin, output, *, work_root):
    if Path(output).exists() or Path(output).is_symlink():
        raise ValueError("Preserve completed evidence; choose a new output path.")
    source = release.code_identity()
    workflow = workflows.check()
    evidence, _ = release.qualification(Path(path), pin, Path(bundle))
    scratch = Path(
        tempfile.mkdtemp(prefix="release-qualification-", dir=external_work_root(work_root))
    )
    store = release.ReleaseStore(scratch / "release-store", bundle)
    backend = ObservedBackend(store.root, bundle, store.scope)
    store.backend = backend
    started = datetime.now(timezone.utc).isoformat()
    complete = False
    try:
        for name in ("local-reference-a", "local-reference-b"):
            store.stage(name, Path(path), pin)
        descriptors = {
            name: json.loads((store.root / "releases" / (name + ".json")).read_text())
            for name in ("local-reference-a", "local-reference-b")
        }
        initial = store.change("local-reference-a")
        descriptor_rejection = reject_invalid_descriptor(store, backend)
        before = (store.root / "active.json").read_bytes()
        try:
            store.stage("rejected", Path(path), "0" * 64)
        except ValueError as error:
            if str(error) != "Qualification pin differs.":
                raise
        else:
            raise ValueError("Wrong qualification pin was accepted.")
        backend.fail_readiness = True
        try:
            store.change("local-reference-b")
        except ValueError as error:
            if str(error) != "controlled readiness observer fault":
                raise
        else:
            raise ValueError("Injected candidate observer fault was accepted.")
        if (
            before != (store.root / "active.json").read_bytes()
            or (store.root / "pending.json").exists()
            or not backend.healthy(
                initial["state"]["active"], store.entry_descriptor(initial["state"]["active"])
            )
        ):
            raise ValueError("Rejected candidate changed the previous active release.")
        backend.fail_retirement = True
        try:
            store.change("local-reference-b")
        except ValueError as error:
            if str(error) != "controlled retirement observer fault":
                raise
        else:
            raise ValueError("Injected postcommit cleanup fault was accepted.")
        committed = store.state()
        if (
            committed["active"]["release_id"] != "local-reference-b"
            or not (store.root / "pending.json").is_file()
        ):
            raise ValueError("Postcommit failure did not retain explicit recovery state.")
        # Kill the committed target BEFORE recovering its unfinished journal.
        # This is an owned container fault, not host/daemon power-loss recovery.
        failed_entry = committed["active"]
        failed_descriptor = store.entry_descriptor(failed_entry)
        backend.owned(failed_entry, failed_descriptor)
        backend.call(["kill", "--signal", "KILL", failed_entry["container_name"]])
        failed_state = backend.owned(failed_entry, failed_descriptor)["State"]
        if failed_state["Running"] or failed_state["ExitCode"] != 137:
            raise ValueError("Controlled active-process termination was not observed.")
        recovered = store.recover()
        if (
            recovered["committed"] is not True
            or recovered.get("retirement_deferred") is not True
            or recovered["state"]["retained"] != [initial["state"]["active"]]
            or not backend.healthy(
                initial["state"]["active"], store.entry_descriptor(initial["state"]["active"])
            )
        ):
            raise ValueError("Compound recovery did not preserve the former active instance.")
        replacement = {
            "state": committed,
            "http": backend.verified[committed["active"]["container_name"]],
            "recovery": recovered,
        }
        rollback = store.change(rollback=True)
        if (
            rollback["state"]["active"]["release_id"] != "local-reference-a"
            or rollback["state"]["active"]["container_id"]
            == initial["state"]["active"]["container_id"]
            or rollback["cleanup"]["prior_already_exited_abnormally"] is not True
            or rollback["cleanup"]["graceful"] is not False
            or len(rollback["cleanup"].get("retained_cleanup", [])) != 1
            or rollback["cleanup"]["retained_cleanup"][0]["graceful"] is not True
            or rollback["state"]["retained"] != []
        ):
            raise ValueError("Rollback did not verify a fresh prior release instance.")
        stopped = store.change(stop=True)
        require_graceful_stop(stopped)
        if (
            stopped["state"]["active"] is not None
            or (store.root / "pending.json").exists()
            or backend.owned_names()
            or stopped["state"]["retained"] != []
        ):
            raise ValueError("Release exercise left owned state or containers active.")
        if release.code_identity() != source or file_sha(path) != pin:
            raise ValueError("Measured release source or upstream evidence changed.")
        release.qualification(Path(path), pin, Path(bundle))
        complete = True
    finally:
        # Dedicated verification store only. Failed runs never publish success.
        if not complete:
            for name in backend.owned_names():
                store.check_name(name)
                state = linux.inspect("container", name, backend.logs)
                if state["Config"]["Labels"].get("recsys.release.scope") != store.scope:
                    raise ValueError("Foreign container during failed-exercise cleanup.")
                linux.remove(name, backend.logs)
    result = {
        "schema_version": 1,
        "verification": "local-snapshot-release-workflow-acceptance-v1",
        "channel": release.CHANNEL,
        "operational_passed": True,
        "deployment_eligible": False,
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "files_lf_sha256": source,
            "qualification_sha256": pin,
            "image_id": evidence["identity"]["image_id"],
            "manifest_sha256": evidence["identity"]["manifest_sha256"],
        },
        "workflow_policy": workflow,
        "descriptors": descriptors,
        "initial": initial,
        "replacement": replacement,
        "rollback": rollback,
        "stop": stopped,
        "rejected_qualification_preserved_active": True,
        "invalid_descriptor_rejection": descriptor_rejection,
        "rejected_descriptor_preserved_active": True,
        "rejected_observer_preserved_active": True,
        "postcommit_journal_recovery_passed": True,
        "rollback_restored_after_active_process_kill": True,
        "compound_recovery_preserved_former_active": True,
        "final_graceful_stop_verified": True,
        "external_recovery_storage": True,
        "owned_containers_remaining": 0,
        "limits": [
            "Two immutable release IDs use the same qualified image/model; control transitions, not a model comparison.",
            "Readiness/retirement observer faults and an owned active-process SIGKILL; no model corruption or host/daemon power-loss test.",
            "Local Docker Desktop Linux, network none, no public traffic switching or zero-downtime claim.",
            "Original Linux qualification is upstream evidence; no new full-fold quality or blind data.",
            "RAM budget remains unmet; representative load, target-host recovery and production rollout remain separate.",
            "Workflow YAML/policy are locally validated; no GitHub run, private runner or environment protection was configured here.",
        ],
    }
    publish(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--qualification-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(
            args.bundle,
            args.qualification,
            args.qualification_sha256,
            args.output,
            work_root=args.work_root,
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(
            1,
            "Local release qualification failed; no success receipt published. Inspect private store logs/journal.\n",
        )
    print(
        json.dumps(
            {
                "operational_passed": True,
                "deployment_eligible": False,
                "output": args.output.as_posix(),
            }
        )
    )


if __name__ == "__main__":
    main()
