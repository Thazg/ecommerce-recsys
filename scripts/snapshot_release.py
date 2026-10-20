"""Immutable local snapshot releases; no registry or public deployment support."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, file_sha, verify_inventory, write_json

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import verify_linux_container as linux  # noqa: E402
from scripts.release_validation import load_receipt  # noqa: E402
from scripts.verify_release import publish  # noqa: E402

CHANNEL = "local-qualification"
STATE_VERSION = 2
MAX_RETAINED = 16
SOURCE_FILES = (
    "scripts/snapshot_release.py",
    "scripts/verify_release_workflow.py",
    "scripts/check_release_workflows.py",
    "scripts/verify_ci_profile.py",
    "tests/unit/test_snapshot_release.py",
    "tests/unit/test_release_workflows.py",
    "tests/unit/test_ci_profile.py",
    "requirements/ci-linux.txt",
    "requirements/release-test.txt",
    ".github/workflows/ci.yml",
    ".github/workflows/snapshot-release.yml",
    ".github/actionlint.yaml",
)


def code_identity():
    # Canonical text identity is stable across checkout newline conversion.
    import hashlib

    return {
        name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in SOURCE_FILES
    }


def release_id(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", value)
        or ".." in value
    ):
        raise ValueError("Release ID must be a bounded simple name.")
    return value


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a trusted lowercase SHA-256.")
    return value


def atomic(path, data):
    descriptor, name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    os.close(descriptor)
    temp = Path(name)
    try:
        write_json(temp, {**data, "content_sha256": digest(data)})
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def operation_lock(root):
    path = root / "operation.lock"
    if path.is_symlink():
        raise ValueError("Lock cannot be a symlink.")
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ValueError("Another release operation owns this store.") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("Another release operation owns this store.") from None
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def qualification(path, pin, bundle):
    sha(pin)
    evidence = load_receipt(path)
    if file_sha(path) != sha(pin):
        raise ValueError("Qualification pin differs.")
    identity = evidence["identity"]
    manifest = verify_inventory(bundle, identity["manifest_sha256"])
    startup = evidence.get("negative_startup")
    if (
        evidence.get("qualification_passed") is not True
        or evidence.get("deployment_eligible") is not False
        or identity["files_sha256"] != linux.sources()
        or identity["base_image"] != linux.BASE
        or evidence.get("container_cleanup_verified") is not True
        or evidence.get("build_context", {}).get("canary_verified") is not True
        or not isinstance(startup, dict)
        or set(startup) != {"bad_pin", "missing", "corrupt"}
        or any(value is not True for value in startup.values())
        or type(evidence.get("graceful_cleanup_events")) is not int
        or evidence["graceful_cleanup_events"] != 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity["image_id"])
    ):
        raise ValueError("Incomplete, stale or foreign Linux qualification.")
    linux.validate_runtime(evidence["runtime"], manifest)
    linux.validate_evidence(
        evidence["model"],
        evidence["http"],
        identity["manifest_sha256"],
        manifest["components"]["references.json"]["sha256"],
    )
    if evidence["resource_policy"] != {
        "uid": 10001,
        "gid": 10001,
        "network": "none",
        "published_ports": False,
        "read_only_root": True,
        "read_only_model": True,
        "capabilities": "all dropped",
        "no_new_privileges": True,
        "pids_limit": 64,
        "cpus": 2,
        "memory_limit_bytes": linux.MEMORY,
        "memory_swap_limit_bytes": linux.MEMORY,
        "tmpfs_bytes": 16777216,
    }:
        raise ValueError("Qualification resource policy differs.")
    return evidence, manifest


class DockerBackend:
    def __init__(self, root, bundle, scope):
        self.logs, self.bundle, self.scope = root / "logs", Path(bundle).absolute(), scope
        self.logs.mkdir(exist_ok=True)

    def call(self, args, **kwargs):
        return linux.docker(["container", *args], self.logs, **kwargs)

    def image(self, descriptor):
        value = linux.inspect("image", descriptor["image_id"], self.logs)
        if linux.validate_image(value) != descriptor["image_id"]:
            raise ValueError("Immutable image identity differs.")

    def exists(self, name):
        result = self.call(["ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"])
        if result.stdout.strip() not in ("", name):
            raise ValueError("Unexpected owned-container enumeration.")
        return bool(result.stdout.strip())

    def owned(self, entry, descriptor):
        state = linux.inspect("container", entry["container_name"], self.logs)
        config = state["Config"]
        labels = config.get("Labels") or {}
        env = dict(value.split("=", 1) for value in config["Env"])
        if (
            labels.get("recsys.release.scope") != self.scope
            or labels.get("recsys.release.id") != descriptor["release_id"]
            or state["Name"] != "/" + entry["container_name"]
            or (entry.get("container_id") is not None and state["Id"] != entry["container_id"])
            or env.get("RECSYS_MANIFEST_SHA256") != descriptor["manifest_sha256"]
            or config["Entrypoint"] != ["python", "-m", "ecommerce_recsys.serving"]
            or config["Cmd"] != ["--bundle-path", "/model", "--port", "8000"]
        ):
            raise ValueError("Container ownership or immutable runtime differs.")
        linux.validate_container(state, descriptor["image_id"])
        return state

    def create(self, entry, descriptor):
        self.image(descriptor)
        self.call(
            [
                "create",
                "--name",
                entry["container_name"],
                "--platform",
                "linux/amd64",
                "--label",
                "recsys.release.scope=" + self.scope,
                "--label",
                "recsys.release.id=" + descriptor["release_id"],
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--cpus",
                "2",
                "--memory",
                "4g",
                "--memory-swap",
                "4g",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777",
                "--stop-timeout",
                "30",
                "--env",
                "RECSYS_MANIFEST_SHA256=" + descriptor["manifest_sha256"],
                "--mount",
                f"type=bind,source={self.bundle},target=/model,readonly",
                descriptor["image_id"],
            ]
        )
        return self.owned(entry, descriptor)["Id"]

    def start(self, entry, descriptor):
        self.owned(entry, descriptor)
        self.call(["start", entry["container_name"]])

    def healthy(self, entry, descriptor):
        if not self.exists(entry["container_name"]):
            return False
        state = self.owned(entry, descriptor)["State"]
        return state.get("Running") is True and state.get("Health", {}).get("Status") == "healthy"

    def verify(self, entry, descriptor, evidence):
        deadline = time.monotonic() + 150
        while not self.healthy(entry, descriptor):
            state = self.owned(entry, descriptor)["State"]
            if not state.get("Running") or time.monotonic() >= deadline:
                raise ValueError("Candidate failed readiness before publication.")
            time.sleep(1)
        response = self.call(
            ["exec", entry["container_name"], "python", "/opt/runtime/probe.py", "http"],
            timeout=180,
        )
        http = json.loads(response.stdout)
        linux.validate_evidence(
            evidence["model"],
            http,
            descriptor["manifest_sha256"],
            evidence["identity"]["references_sha256"],
        )
        if http["outputs_sha256"] != evidence["http"]["outputs_sha256"]:
            raise ValueError("Candidate HTTP outputs differ from qualification.")
        return http

    def remove(self, entry, descriptor, *, graceful):
        events = 0
        stopped_cleanly = False
        prior_failed = False
        if self.exists(entry["container_name"]):
            state = self.owned(entry, descriptor)
            if graceful:
                running = state["State"]["Running"]
                if running:
                    self.call(["stop", "--time", "30", entry["container_name"]], timeout=45)
                state = self.owned(entry, descriptor)["State"]
                logs = self.call(["logs", entry["container_name"]])
                events = sum(
                    json.loads(line)["event"] == "cleanup_complete"
                    for line in logs.stderr.splitlines()
                    if line.startswith('{"event":')
                )
                stopped_cleanly = (
                    not state["Running"]
                    and not state["OOMKilled"]
                    and state["ExitCode"] in (0, 143)
                    and events == 1
                )
                # An already exited former active may be retired after rollback.
                # Never report its abnormal exit as successful graceful drain.
                prior_failed = not running and not stopped_cleanly
                if state["Running"] or (running and not stopped_cleanly):
                    raise ValueError("Owned release did not stop gracefully.")
            linux.remove(entry["container_name"], self.logs)
        if self.exists(entry["container_name"]):
            raise ValueError("Owned release remains after removal.")
        return {
            "removed": True,
            "graceful": stopped_cleanly,
            "prior_already_exited_abnormally": prior_failed,
            "cleanup_events": events,
        }


class ReleaseStore:
    def __init__(self, root, bundle, backend=None):
        supplied = Path(root).absolute()
        if any(p.is_symlink() for p in [supplied, *supplied.parents]):
            raise ValueError("Release store cannot traverse symlinks.")
        supplied.mkdir(parents=True, exist_ok=True)
        self.root, self.bundle = supplied, Path(bundle).absolute()
        self.scope = digest(
            str(supplied.resolve()).casefold() if os.name == "nt" else str(supplied.resolve())
        )
        for name in ("releases", "evidence"):
            path = supplied / name
            if path.is_symlink():
                raise ValueError("Release directories cannot be symlinks.")
            path.mkdir(exist_ok=True)
        self.backend = backend or DockerBackend(supplied, self.bundle, self.scope)

    def descriptor(self, value, pin=None):
        name = release_id(value)
        path = self.root / "releases" / (name + ".json")
        data = load_receipt(path)
        if pin is not None and file_sha(path) != sha(pin):
            raise ValueError("Release descriptor pin differs.")
        if (
            set(data)
            != {
                "schema_version",
                "kind",
                "channel",
                "release_id",
                "image_id",
                "manifest_sha256",
                "bundle_version",
                "qualification_sha256",
                "controller_sha256",
                "content_sha256",
            }
            or type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["kind"] != "snapshot-release-v1"
            or data["channel"] != CHANNEL
            or data["release_id"] != name
            or data["controller_sha256"] != digest(code_identity())
        ):
            raise ValueError("Release descriptor/source contract differs.")
        qpin = sha(data["qualification_sha256"])
        evidence, manifest = qualification(
            self.root / "evidence" / (qpin + ".json"), qpin, self.bundle
        )
        if (
            data["image_id"] != evidence["identity"]["image_id"]
            or data["manifest_sha256"] != evidence["identity"]["manifest_sha256"]
            or data["bundle_version"] != manifest["bundle_version"]
        ):
            raise ValueError("Descriptor image/model differs from qualified identity.")
        return data, evidence

    def stage(self, name, path, pin):
        name = release_id(name)
        with operation_lock(self.root):
            self.no_pending()
            evidence, manifest = qualification(Path(path), pin, self.bundle)
            data = {
                "schema_version": 1,
                "kind": "snapshot-release-v1",
                "channel": CHANNEL,
                "release_id": name,
                "image_id": evidence["identity"]["image_id"],
                "manifest_sha256": evidence["identity"]["manifest_sha256"],
                "bundle_version": manifest["bundle_version"],
                "qualification_sha256": pin,
                "controller_sha256": digest(code_identity()),
            }
            self.backend.image(data)
            target = self.root / "evidence" / (pin + ".json")
            if target.is_symlink():
                raise ValueError("Stored qualification cannot be a symlink.")
            if not target.exists():
                fd, name_tmp = tempfile.mkstemp(prefix=".evidence-", dir=target.parent)
                temp = Path(name_tmp)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(Path(path).read_bytes())
                        stream.flush()
                        os.fsync(stream.fileno())
                    if file_sha(temp) != pin:
                        raise ValueError("Qualification changed during staging.")
                    os.link(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            if target.is_symlink() or file_sha(target) != pin:
                raise ValueError("Stored qualification bytes differ.")
            publish(self.root / "releases" / (name + ".json"), data)
            return data

    def state(self):
        path = self.root / "active.json"
        if not path.exists() and not path.is_symlink():
            return {
                "schema_version": STATE_VERSION,
                "channel": CHANNEL,
                "scope": self.scope,
                "generation": 0,
                "active": None,
                "previous": None,
                "retained": [],
            }
        data = load_receipt(path)
        data.pop("content_sha256")
        return self.validate_state(data)

    def validate_state(self, data, *, uncreated=False):
        if (
            not isinstance(data, dict)
            or set(data)
            != {
                "schema_version",
                "channel",
                "scope",
                "generation",
                "active",
                "previous",
                "retained",
            }
            or type(data["schema_version"]) is not int
            or data["schema_version"] != STATE_VERSION
            or data["channel"] != CHANNEL
            or data["scope"] != self.scope
            or type(data["generation"]) is not int
            or not 0 <= data["generation"] < 2**63
            or not isinstance(data["retained"], list)
            or len(data["retained"]) > MAX_RETAINED
        ):
            raise ValueError("Active state contract differs.")
        entries = [("active", data["active"]), ("previous", data["previous"])] + [
            ("retained", entry) for entry in data["retained"]
        ]
        names = set()
        for key, entry in entries:
            if entry is None:
                if key == "retained":
                    raise ValueError("Retained ownership cannot be empty.")
                continue
            expected = {"release_id", "descriptor_sha256"} | (
                {"container_name", "container_id"} if key != "previous" else set()
            )
            if not isinstance(entry, dict) or set(entry) != expected:
                raise ValueError("Active/previous entry contract differs.")
            release_id(entry["release_id"])
            sha(entry["descriptor_sha256"])
            if key != "previous":
                self.check_name(entry["container_name"])
                if entry["container_name"] in names:
                    raise ValueError("Duplicate active/retained container ownership.")
                names.add(entry["container_name"])
                if not (key == "active" and uncreated and entry["container_id"] is None):
                    sha(entry["container_id"])
        return data

    def validate_journal(self, journal):
        if (
            not isinstance(journal, dict)
            or set(journal) != {"schema_version", "scope", "prior", "target", "candidate", "phase"}
            or type(journal["schema_version"]) is not int
            or journal["schema_version"] != STATE_VERSION
            or journal["scope"] != self.scope
            or journal["phase"] not in {"prepared", "created", "verified", "committed"}
        ):
            raise ValueError("Foreign or malformed recovery journal.")
        prior = self.validate_state(journal["prior"])
        target = self.validate_state(journal["target"], uncreated=journal["phase"] == "prepared")
        previous = (
            {k: prior["active"][k] for k in ("release_id", "descriptor_sha256")}
            if prior["active"]
            else prior["previous"]
        )
        candidate = journal["candidate"]
        if (
            target["generation"] != prior["generation"] + 1
            or target["previous"] != previous
            or target["active"] != candidate
            or target["retained"] != []
            or (
                candidate is None
                and (prior["active"] is None or journal["phase"] not in {"prepared", "committed"})
            )
            or (
                candidate is not None
                and candidate["container_name"]
                in {
                    entry["container_name"]
                    for entry in [prior["active"], *prior["retained"]]
                    if entry is not None
                }
            )
        ):
            raise ValueError("Inconsistent journal transition; refusing cleanup.")
        return journal

    def check_name(self, name):
        if not isinstance(name, str) or not re.fullmatch(
            "recsys-release-" + self.scope[:12] + r"-[0-9a-f]{12}", name
        ):
            raise ValueError("Container name is outside this release store.")

    def no_pending(self):
        if (self.root / "pending.json").exists() or (self.root / "pending.json").is_symlink():
            raise ValueError("An incomplete operation requires explicit recovery.")

    def entry_descriptor(self, entry):
        self.check_name(entry["container_name"])
        return self.descriptor(entry["release_id"], entry["descriptor_sha256"])[0]

    def require_active(self, state):
        if state["active"] is not None and not self.backend.healthy(
            state["active"], self.entry_descriptor(state["active"])
        ):
            raise ValueError("Prior active release is not healthy; explicit recovery is required.")

    def deferred_state(self, journal):
        """Keep prior instances owned when committed target cannot safely retire them."""
        self.validate_journal(journal)
        target, prior = journal["target"], journal["prior"]
        if target["active"] is None or target["generation"] >= 2**63 - 1:
            raise ValueError("Committed state cannot defer retirement.")
        retained = [*prior["retained"]]
        if prior["active"] is not None:
            retained.append(prior["active"])
        return self.validate_state(
            {
                **target,
                "generation": target["generation"] + 1,
                "retained": retained,
            }
        )

    def finish(self, journal, *, committed):
        self.validate_journal(journal)
        state = self.state()
        if state != journal["target" if committed else "prior"]:
            raise ValueError("Ambiguous pointer/journal state; refusing cleanup.")
        if committed:
            self.require_active(state)
        cleanup = None
        entry = journal["prior"]["active"] if committed else journal["candidate"]
        if entry is not None:
            cleanup = self.backend.remove(entry, self.entry_descriptor(entry), graceful=committed)
        if committed and journal["prior"]["retained"]:
            retained_cleanup = [
                self.backend.remove(entry, self.entry_descriptor(entry), graceful=True)
                for entry in journal["prior"]["retained"]
            ]
            cleanup = {**(cleanup or {}), "retained_cleanup": retained_cleanup}
        (self.root / "pending.json").unlink()
        return cleanup

    def change(self, name=None, *, rollback=False, stop=False):
        with operation_lock(self.root):
            self.no_pending()
            prior = self.state()
            if prior["generation"] >= 2**63 - 1 or (rollback and stop):
                raise ValueError("Invalid operation flags or exhausted generation counter.")
            if not stop and not rollback:
                self.require_active(prior)
            if stop and prior["active"] is None and not prior["retained"]:
                return {"state": prior, "http": None, "cleanup": None}
            if rollback:
                if prior["previous"] is None:
                    raise ValueError("No previous release is available.")
                name = prior["previous"]["release_id"]
                self.descriptor(name, prior["previous"]["descriptor_sha256"])
            descriptor, evidence = self.descriptor(name) if not stop else (None, None)
            candidate = (
                None
                if stop
                else {
                    "release_id": name,
                    "descriptor_sha256": file_sha(self.root / "releases" / (name + ".json")),
                    "container_name": "recsys-release-"
                    + self.scope[:12]
                    + "-"
                    + uuid.uuid4().hex[:12],
                    "container_id": None,
                }
            )
            previous = (
                {k: prior["active"][k] for k in ("release_id", "descriptor_sha256")}
                if prior["active"]
                else prior["previous"]
            )
            target = {
                **prior,
                "generation": prior["generation"] + 1,
                "active": candidate,
                "previous": previous,
                "retained": [],
            }
            journal = {
                "schema_version": STATE_VERSION,
                "scope": self.scope,
                "prior": prior,
                "target": target,
                "candidate": candidate,
                "phase": "prepared",
            }
            atomic(self.root / "pending.json", journal)
            try:
                http = None
                if candidate:
                    candidate["container_id"] = self.backend.create(candidate, descriptor)
                    sha(candidate["container_id"])
                    journal["phase"] = "created"
                    atomic(self.root / "pending.json", journal)
                    self.backend.start(candidate, descriptor)
                    http = self.backend.verify(candidate, descriptor, evidence)
                    if not self.backend.healthy(candidate, descriptor):
                        raise ValueError("Candidate lost readiness before pointer publication.")
                    journal["phase"] = "verified"
                    atomic(self.root / "pending.json", journal)
                atomic(self.root / "active.json", target)
                journal["phase"] = "committed"
                atomic(self.root / "pending.json", journal)
                cleanup = self.finish(journal, committed=True)
                return {"state": target, "http": http, "cleanup": cleanup}
            except BaseException:
                if self.state() == prior:
                    self.finish(journal, committed=False)
                raise

    def recover(self):
        with operation_lock(self.root):
            journal = load_receipt(self.root / "pending.json")
            journal.pop("content_sha256")
            self.validate_journal(journal)
            state = self.state()
            if state == journal["prior"]:
                cleanup = self.finish(journal, committed=False)
                return {"state": self.state(), "committed": False, "cleanup": cleanup}
            if state == journal["target"] and (
                state["active"] is not None
                and not self.backend.healthy(
                    state["active"], self.entry_descriptor(state["active"])
                )
            ):
                # No container is removed. Persist exact retained ownership before
                # removing the old journal; a crash in between is idempotently recoverable.
                deferred = self.deferred_state(journal)
                atomic(self.root / "active.json", deferred)
                (self.root / "pending.json").unlink()
                return {
                    "state": deferred,
                    "committed": True,
                    "retirement_deferred": True,
                    "cleanup": None,
                }
            if state == journal["target"]:
                cleanup = self.finish(journal, committed=True)
                return {"state": self.state(), "committed": True, "cleanup": cleanup}
            if journal["target"]["active"] and journal["phase"] != "prepared":
                deferred = self.deferred_state(journal)
                if state == deferred:
                    (self.root / "pending.json").unlink()
                    return {
                        "state": deferred,
                        "committed": True,
                        "retirement_deferred": True,
                        "cleanup": None,
                    }
            raise ValueError("Pointer does not match either journal state.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--release-id", required=True)
    stage.add_argument("--qualification", type=Path, required=True)
    stage.add_argument("--qualification-sha256", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--release-id", required=True)
    for command in ("rollback", "recover", "stop", "status"):
        commands.add_parser(command)
    args = parser.parse_args()
    try:
        store = ReleaseStore(args.store, args.bundle)
        if args.command == "stage":
            result = store.stage(args.release_id, args.qualification, args.qualification_sha256)
        elif args.command == "activate":
            result = store.change(args.release_id)
        elif args.command in {"rollback", "stop"}:
            result = store.change(**{args.command: True})
        elif args.command == "recover":
            result = store.recover()
        else:
            with operation_lock(store.root):
                result = {
                    "state": store.state(),
                    "recovery_required": (store.root / "pending.json").exists(),
                }
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "Local release operation failed; inspect private journal/logs.\n")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
