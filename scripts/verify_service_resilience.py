"""Verify fixed load, startup faults, owned drain and fresh snapshot recovery."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from ecommerce_recsys.artifacts.contract import digest, file_sha

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import benchmark_http_capacity as capacity  # noqa: E402
from scripts import check_release_workflows as gates  # noqa: E402
from scripts import service_resilience_workload as workload  # noqa: E402
from scripts import snapshot_release as release  # noqa: E402
from scripts import verify_linux_container as linux  # noqa: E402
from scripts import verify_release_workflow as recovery  # noqa: E402
from scripts.release_validation import load_receipt  # noqa: E402
from scripts.verify_release import publish  # noqa: E402

CAPACITY = ROOT / "benchmarks/performance/http_capacity_boundary_validation_v1.json"
CAPACITY_PIN = "d239ecad08f244fb58b28cbdbf545f3db4789f5f36d1c9cbbb119a65d022aaf1"
FILES = (
    "scripts/service_resilience_workload.py",
    "scripts/verify_service_resilience.py",
    "tests/unit/test_service_resilience.py",
    "tests/integration/test_resilience_process.py",
    *capacity.FILES,
)
STEPS = (
    *(cell["name"] for cell in workload.CELLS),
    "client-disconnect",
    "inflight-drain",
    "startup-bad-pin",
    "startup-missing",
    "startup-corrupt",
    "release-recovery",
)


def source_identity():
    return {name: file_sha(ROOT / name) for name in FILES}


def driver_source():
    helper = (ROOT / "scripts/http_capacity_workload.py").read_text(encoding="utf-8")
    code = (ROOT / "scripts/service_resilience_workload.py").read_text(encoding="utf-8")
    return code.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\n_CAPACITY_SOURCE = " + repr(helper),
        1,
    )


def bounded(value, maximum, *, positive=False):
    return (
        type(value) in (int, float)
        and (0 < value if positive else 0 <= value)
        and value <= maximum
        and math.isfinite(value)
    )


def validate_cleanup(value, *, graceful):
    if (
        not isinstance(value, dict)
        or value.get("removed") is not True
        or type(value.get("cleanup_events")) is not int
        or value.get("graceful") is not graceful
        or value.get("prior_already_exited_abnormally") is not False
        or value["cleanup_events"] != (1 if graceful else 0)
    ):
        raise ValueError("Resilience owned cleanup proof differs.")


def validate_result(row, step, references):
    if step not in STEPS or row.get("step") != step:
        raise ValueError("Incomplete or foreign resilience step.")
    if step == "release-recovery":
        release.sha(row.get("receipt_file_sha256"))
        child = row.get("receipt", {})
        if (
            child.get("operational_passed") is not True
            or child.get("external_recovery_storage") is not True
            or type(child.get("owned_containers_remaining")) is not int
            or child.get("owned_containers_remaining") != 0
            or child.get("identity", {}).get("files_lf_sha256") != release.code_identity()
            or child.get("identity", {}).get("qualification_sha256") != capacity.QUALIFICATION_PIN
            or child.get("final_graceful_stop_verified") is not True
            or child.get("rollback_restored_after_active_process_kill") is not True
            or child.get("postcommit_journal_recovery_passed") is not True
            or child.get("rejected_descriptor_preserved_active") is not True
            or row.get("receipt_payload_sha256") != digest(child)
            or not bounded(row.get("exercise_seconds"), 1000, positive=True)
            or child.get("content_sha256")
            != digest({k: v for k, v in child.items() if k != "content_sha256"})
        ):
            raise ValueError("Fresh recovery evidence is incomplete or foreign.")
        recovery.require_graceful_stop(child["stop"])
        qualified = load_receipt(capacity.QUALIFICATION)
        if (
            child["identity"].get("manifest_sha256") != qualified["identity"]["manifest_sha256"]
            or child["identity"].get("image_id") != qualified["identity"]["image_id"]
            or child.get("compound_recovery_preserved_former_active") is not True
            or child.get("rejected_observer_preserved_active") is not True
            or child.get("rejected_qualification_preserved_active") is not True
            or any(
                child.get("invalid_descriptor_rejection", {}).get(k) is not True
                for k in (
                    "valid_content_checksum",
                    "active_pointer_unchanged",
                    "owned_names_unchanged",
                    "no_pending_journal",
                    "active_healthy",
                )
            )
        ):
            raise ValueError("Recovery identity or fault preservation differs.")
        for key in ("initial", "replacement", "rollback"):
            if child[key]["http"].get("outputs_sha256") != qualified["http"]["outputs_sha256"]:
                raise ValueError("Recovery HTTP outputs differ from the sealed qualification.")
            linux.validate_evidence(
                qualified["model"],
                child[key]["http"],
                qualified["identity"]["manifest_sha256"],
                qualified["identity"]["references_sha256"],
            )
        return row
    if not bounded(row.get("startup_seconds"), 150, positive=True):
        raise ValueError("Missing bounded actual startup/exit measurement.")
    fault = step.startswith("startup-")
    validate_cleanup(row.get("cleanup"), graceful=not fault)
    if fault:
        state = row.get("failure", {})
        if (
            state.get("kind") != step.removeprefix("startup-")
            or type(state.get("exit_code")) is not int
            or state["exit_code"] == 0
            or state.get("oom_killed") is not False
            or state.get("ever_healthy") is not False
            or not bounded(
                state.get("exit_seconds"), workload.POLICY["invalid_startup_seconds"], positive=True
            )
        ):
            raise ValueError("Invalid model dependency was not rejected as declared.")
        return row
    if row.get("driver_payload_sha256") != digest(driver_source()):
        raise ValueError("Resilience driver payload differs.")
    data = row["result"]
    if data.get("pre_references") != len(references):
        raise ValueError("Missing complete pre-reference coverage.")
    cell = next((c for c in workload.CELLS if c["name"] == step), None)
    if cell:
        if (
            data.get("cell") != cell
            or data.get("parity_passed") is not True
            or data.get("post_references") != len(references)
            or len(data.get("phases", [])) != len(cell["phases"])
            or type(data.get("cgroup_memory_peak_bytes")) is not int
            or not 0 < data["cgroup_memory_peak_bytes"] <= linux.MEMORY
        ):
            raise ValueError("Resilience load matrix is incomplete.")
        pressure = data["pressure"]
        if (
            type(pressure.get("allocated_bytes")) is not int
            or pressure["allocated_bytes"] != cell["pressure_bytes"]
            or any(
                type(pressure.get(k)) is not int or not 0 < pressure[k] < 2**63
                for k in ("driver_rss_before_bytes", "driver_rss_occupied_bytes")
            )
        ):
            raise ValueError("Invalid memory pressure evidence.")
        if cell["pressure_bytes"] and (
            pressure["driver_rss_occupied_bytes"] - pressure["driver_rss_before_bytes"]
            < cell["pressure_bytes"] * 0.9
        ):
            raise ValueError("Required memory occupancy was not observed.")
        for result, phase in zip(data["phases"], cell["phases"], strict=True):
            workload.validate_window(result, phase, references)
            if phase["name"].startswith("quiet-"):
                evidence = result.get("recovery", {})
                if (
                    evidence.get("references") != 2
                    or evidence.get("ready_and_drained") is not True
                    or not bounded(
                        evidence.get("seconds"), workload.POLICY["recovery_seconds"], positive=True
                    )
                ):
                    raise ValueError("Missing timely post-burst recovery pair.")
        return row
    if data.get("kind") != step or data.get("primary_witnessed") is not True:
        raise ValueError("Lifecycle requires an actual in-flight primary observation.")
    if step == "client-disconnect":
        if (
            data.get("post_references") != len(references)
            or data.get("parity_passed") is not True
            or data.get("ready_and_drained") is not True
            or not bounded(data.get("drain_seconds"), workload.POLICY["recovery_seconds"])
        ):
            raise ValueError("Disconnected numerical worker did not recover.")
    elif (
        data.get("signal") != "SIGTERM"
        or data.get("accepted_response_parity") is not True
        or not bounded(
            data.get("observation_to_signal_seconds"), workload.POLICY["signal_lag_seconds"]
        )
    ):
        raise ValueError("Accepted in-flight work was not verified during graceful drain.")
    return row


class StartupBackend(capacity.CapacityBackend):
    """Narrow, verifier-only startup file faults with independent ownership checks."""

    def __init__(self, root, bundle, scope, kind):
        if (root / "logs").is_symlink() or (root / "corrupt-weights.npy").is_symlink():
            raise ValueError("Fault scratch paths cannot be symlinks.")
        super().__init__(root, bundle, scope, False)
        if kind not in {"bad-pin", "missing", "corrupt"}:
            raise ValueError("Unknown controlled startup fault.")
        self.kind, self.corrupt = kind, root / "corrupt-weights.npy"
        if kind == "corrupt":
            self.corrupt.write_bytes(b"resilience-controlled-invalid-weight-array")

    def call(self, args, **kwargs):
        args = list(args)
        if args[0] == "create":
            if self.kind == "missing":
                index = args.index("--mount")
                del args[index : index + 2]
            if self.kind == "bad-pin":
                args = [
                    "RECSYS_MANIFEST_SHA256=" + "0" * 64
                    if v.startswith("RECSYS_MANIFEST_SHA256=")
                    else v
                    for v in args
                ]
            if self.kind == "corrupt":
                args = [
                    *args[:-1],
                    "--mount",
                    f"type=bind,source={self.corrupt.resolve()},target=/model/weights.npy,readonly",
                    args[-1],
                ]
        return super().call(args, **kwargs)

    def owned(self, entry, descriptor):
        state = linux.inspect("container", entry["container_name"], self.logs)
        config, host = state["Config"], state["HostConfig"]
        labels = config.get("Labels") or {}
        env = dict(v.split("=", 1) for v in config["Env"])
        expected_pin = "0" * 64 if self.kind == "bad-pin" else descriptor["manifest_sha256"]
        expected = {} if self.kind == "missing" else {"/model": self.bundle}
        if self.kind == "corrupt":
            expected["/model/weights.npy"] = self.corrupt.resolve()
        mounts = host.get("Mounts", [])
        if (
            state["Name"] != "/" + entry["container_name"]
            or (entry.get("container_id") is not None and state["Id"] != entry["container_id"])
            or labels.get("recsys.release.scope") != self.scope
            or labels.get("recsys.release.id") != descriptor["release_id"]
            or config["Cmd"] != self.command
            or config["Entrypoint"] != ["python", "-m", "ecommerce_recsys.serving"]
            or env.get("RECSYS_MANIFEST_SHA256") != expected_pin
            or any(k.startswith("RECSYS_API_TOKEN") for k in env)
            or len(mounts) != len(expected)
            or {m["Target"] for m in mounts} != set(expected)
            or any(
                m.get("ReadOnly") is not True
                or m["Type"] != "bind"
                or Path(m["Source"]).resolve() != expected[m["Target"]].resolve()
                for m in mounts
            )
            or len(state["Mounts"]) != len(expected)
            or {m["Destination"] for m in state["Mounts"]} != set(expected)
            or any(m["RW"] is not False or m["Type"] != "bind" for m in state["Mounts"])
        ):
            raise ValueError("Startup fault container ownership/mount/pin differs.")
        # Actual fault mounts were checked above. Reuse only the frozen common
        # isolation/resource checks, whose ordinary contract requires /model.
        common = copy.deepcopy(state)
        common["Mounts"] = [{"Destination": "/model", "RW": False, "Type": "bind"}]
        linux.validate_container(common, descriptor["image_id"])
        return state


def run_step(step, bundle, qualification, scratch):
    if any((scratch / name).is_symlink() for name in ("logs", "owned.json")):
        raise ValueError("Owned scratch state cannot be a symlink.")
    scope = digest({"scratch": str(scratch.resolve()), "step": step})
    fault = step.startswith("startup-")
    backend = (
        StartupBackend(scratch, bundle, scope, step.removeprefix("startup-"))
        if fault
        else capacity.CapacityBackend(scratch, bundle, scope, False)
    )
    descriptor = {
        "release_id": step,
        "image_id": qualification["identity"]["image_id"],
        "manifest_sha256": qualification["identity"]["manifest_sha256"],
    }
    entry = {
        "container_name": "recsys-resilience-" + scope[:12] + "-" + uuid.uuid4().hex[:12],
        "container_id": None,
    }
    journal = scratch / "owned.json"
    release.atomic(journal, {"entry": entry, "descriptor": descriptor, "scope": scope})
    started, result = time.monotonic(), None
    try:
        entry["container_id"] = backend.create(entry, descriptor)
        release.atomic(journal, {"entry": entry, "descriptor": descriptor, "scope": scope})
        backend.start(entry, descriptor)
        deadline = started + (
            workload.POLICY["invalid_startup_seconds"]
            if fault
            else workload.POLICY["startup_seconds"]
        )
        ever_healthy = False
        while True:
            state = backend.owned(entry, descriptor)["State"]
            ever_healthy |= state.get("Health", {}).get("Status") == "healthy"
            if fault and not state["Running"]:
                if state["ExitCode"] == 0 or state["OOMKilled"] or ever_healthy:
                    raise ValueError("Controlled invalid startup was not rejected cleanly.")
                result = {
                    "failure": {
                        "kind": step.removeprefix("startup-"),
                        "exit_code": state["ExitCode"],
                        "oom_killed": state["OOMKilled"],
                        "ever_healthy": ever_healthy,
                        "exit_seconds": time.monotonic() - started,
                    }
                }
                break
            if not fault and ever_healthy:
                break
            if time.monotonic() > deadline or (not fault and not state["Running"]):
                raise ValueError("Resilience startup/exit deadline exceeded.")
            time.sleep(0.25)
        startup = time.monotonic() - started
        if not fault:
            payload = driver_source()
            command = [
                "docker",
                "container",
                "exec",
                "-i",
                entry["container_name"],
                "python",
                "-",
                "--profile",
                step,
                "--manifest-sha256",
                descriptor["manifest_sha256"],
            ]
            response = subprocess.run(
                command,
                input=payload,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=1000,
                check=False,
            )
            (backend.logs / "driver.log").write_text(
                response.stdout + response.stderr, encoding="utf-8"
            )
            if response.returncode != 0 and not (
                step == "inflight-drain" and response.returncode in (137, 143)
            ):
                raise ValueError("Resilience driver failed; inspect private log.")
            result = {
                "result": json.loads(response.stdout),
                "driver_payload_sha256": digest(payload),
            }
            if step == "inflight-drain":
                deadline = time.monotonic() + workload.POLICY["stop_seconds"]
                while backend.owned(entry, descriptor)["State"]["Running"]:
                    if time.monotonic() > deadline:
                        raise ValueError("In-flight SIGTERM did not terminate the owned service.")
                    time.sleep(0.05)
    finally:
        cleanup = backend.remove(entry, descriptor, graceful=result is not None and not fault)
        if result is not None:
            validate_cleanup(cleanup, graceful=not fault)
        journal.unlink()
    return {"step": step, "startup_seconds": startup, **result, "cleanup": cleanup}


def collection_sources():
    """Bind collection to all test modules, conftests and pytest configuration."""
    paths = [ROOT / "pyproject.toml", *sorted((ROOT / "tests").rglob("*.py"))]
    return tuple(
        (
            p.relative_to(ROOT).as_posix(),
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        )
        for p in paths
    )


@lru_cache(maxsize=4)
def collected_cases(profile, source):
    if profile not in {"unit", "fixture"} or source != collection_sources():
        raise ValueError("Unknown or changed test collection source.")
    # Use pytest's own JUnit naming, including class names and parameter IDs.
    # Collection runs in a child so it cannot mutate the verifier's pytest state.
    script = """
import json, sys
import pytest
from _pytest.junitxml import mangle_test_address
class Inventory:
    def pytest_collection_finish(self, session):
        self.cases = []
        for item in session.items:
            parts = mangle_test_address(item.nodeid)
            self.cases.append([".".join(parts[:-1]), parts[-1]])
inventory = Inventory()
args = ["--collect-only", "-q", "-o", "addopts=", "tests/" + ("unit" if sys.argv[1] == "unit" else "integration")]
if sys.argv[1] == "fixture":
    args += ["-m", "not real_bundle"]
status = pytest.main(args, plugins=[inventory])
if status != 0:
    sys.exit(int(status))
print("RESILIENCE_COLLECTION=" + json.dumps(inventory.cases))
"""
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""}
    env.pop("PYTEST_PLUGINS", None)
    result = subprocess.run(
        [sys.executable, "-c", script, profile],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    prefix = "RESILIENCE_COLLECTION="
    lines = [line[len(prefix) :] for line in result.stdout.splitlines() if line.startswith(prefix)]
    if len(lines) != 1 or source != collection_sources():
        raise ValueError("Missing or changed complete test collection.")
    rows = json.loads(lines[0])
    if (
        not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(row, list)
            or len(row) != 2
            or any(not isinstance(value, str) or not value for value in row)
            for row in rows
        )
    ):
        raise ValueError("Invalid collected test identities.")
    cases = frozenset(tuple(row) for row in rows)
    if len(cases) != len(rows):
        raise ValueError("Duplicate collected test identity.")
    return cases


def require_complete_profile(path, profile, expected):
    actual = {(node.get("classname"), node.get("name")) for node in ET.parse(path).iter("testcase")}
    if actual != expected:
        raise ValueError(f"The {profile} JUnit differs from the complete collected profile.")


def test_evidence(unit, fixture, linux_path):
    if any(value is None for value in (unit, fixture, linux_path)):
        raise ValueError("Explicit full unit/fixture JUnit and Linux CI evidence are required.")
    paths = [Path(unit), Path(fixture), Path(linux_path)]
    if any(p.is_symlink() for p in paths):
        raise ValueError("Test evidence cannot be a symlink.")
    windows = gates.profiles(paths[0], paths[1])
    collection = collection_sources()
    expected = {profile: collected_cases(profile, collection) for profile in ("unit", "fixture")}
    for path, profile in zip(paths[:2], ("unit", "fixture"), strict=True):
        require_complete_profile(path, profile, expected[profile])
    linux_ci = load_receipt(paths[2])
    if (
        linux_ci.get("functional_passed") is not True
        or linux_ci.get("owned_container_cleanup_verified") is not True
        or linux_ci.get("identity", {}).get("files_lf_sha256") != release.code_identity()
        or any(
            linux_ci.get("identity", {}).get("ci_inputs_sha256", {}).get(name)
            != file_sha(ROOT / name)
            for name in {*FILES, *(name for name, _ in collection)}
        )
        or any(
            linux_ci.get("profiles", {}).get(profile, {}).get("all_passed") is not True
            or type(linux_ci["profiles"][profile].get("passed")) is not int
            or linux_ci["profiles"][profile]["passed"] <= 0
            or linux_ci["profiles"][profile].get("skipped") != 0
            or linux_ci["profiles"][profile].get("tests") != len(expected[profile])
            or linux_ci["profiles"][profile]["passed"] != len(expected[profile])
            for profile in ("unit", "fixture")
        )
    ):
        raise ValueError("Current full Linux test/source evidence is missing or inconsistent.")
    return {
        "inputs_sha256": {
            "unit_junit": file_sha(paths[0]),
            "fixture_junit": file_sha(paths[1]),
            "linux_ci_receipt": file_sha(paths[2]),
        },
        "windows_profiles": windows,
        "linux_profiles": linux_ci["profiles"],
        "collection_sources_sha256": digest(collection),
        "collected_cases_sha256": {
            profile: digest(sorted(cases)) for profile, cases in expected.items()
        },
    }


def identity(bundle, manifest_pin, root, verified_tests):
    if file_sha(CAPACITY) != CAPACITY_PIN:
        raise ValueError("Pinned completed capacity receipt changed.")
    prior = load_receipt(CAPACITY)
    if (
        prior.get("assessment_completed") is not True
        or prior["identity"]["files_sha256"] != capacity.source_identity()
        or prior["identity"]["manifest_sha256"] != manifest_pin
        or prior["identity"]["controller_files_lf_sha256"] != release.code_identity()
    ):
        raise ValueError("Current completed capacity evidence differs.")
    for row, cell in zip(prior["cells"], capacity.workload.CELLS, strict=True):
        capacity.verify_cell(row, cell)
    return {
        "files_sha256": source_identity(),
        "policy_sha256": digest(
            {"policy": workload.POLICY, "cells": workload.CELLS, "steps": STEPS}
        ),
        "capacity_receipt_sha256": file_sha(CAPACITY),
        "qualification_sha256": capacity.QUALIFICATION_PIN,
        "controller_files_lf_sha256": release.code_identity(),
        "manifest_sha256": manifest_pin,
        "bundle_path": str(bundle.resolve()),
        "machine": capacity.machine_identity(root),
        "verification_evidence": verified_tests,
    }


def load_progress(path, expected, references):
    if path.is_symlink():
        raise ValueError("Resilience checkpoint cannot be a symlink.")
    if not path.exists():
        return {"identity": expected, "steps": []}
    data = load_receipt(path)
    if (
        data.get("identity") != expected
        or not isinstance(data.get("steps"), list)
        or len(data["steps"]) > len(STEPS)
    ):
        raise ValueError("Resilience checkpoint source/policy/input identity differs.")
    for row, step in zip(data["steps"], STEPS):
        validate_result(row, step, references)
        if step == "release-recovery":
            child_path = path.parent / step / "release_workflow.json"
            if (
                child_path.is_symlink()
                or file_sha(child_path) != row.get("receipt_file_sha256")
                or load_receipt(child_path) != row["receipt"]
            ):
                raise ValueError("Resumed recovery child file differs from its pinned payload.")
    return {"identity": expected, "steps": data["steps"]}


def verify(
    bundle, manifest_pin, output, work_root, *, unit_junit=None, fixture_junit=None, linux_ci=None
):
    output, bundle = Path(output), Path(bundle).resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("Preserve completed resilience receipts; choose a new path.")
    verified_tests = test_evidence(unit_junit, fixture_junit, linux_ci)
    root = recovery.external_work_root(work_root)
    with release.operation_lock(root):
        qualification, manifest = release.qualification(
            capacity.QUALIFICATION, capacity.QUALIFICATION_PIN, bundle
        )
        if manifest_pin != qualification["identity"]["manifest_sha256"]:
            raise ValueError("Resilience model manifest differs.")
        references = json.loads((bundle / "references.json").read_text(encoding="utf-8"))
        expected = identity(bundle, manifest_pin, root, verified_tests)
        checkpoint = root / "checkpoint.json"
        progress = load_progress(checkpoint, expected, references)
        if any(root.rglob("owned.json")):
            raise ValueError("Unfinished resilience ownership requires explicit inspection.")
        for step in STEPS[len(progress["steps"]) :]:
            scratch = root / step
            if scratch.is_symlink():
                raise ValueError("Resilience step directory cannot be a symlink.")
            scratch.mkdir(exist_ok=True)
            if step == "release-recovery":
                child_path = scratch / "release_workflow.json"
                start = time.monotonic()
                recovery.verify(
                    bundle,
                    capacity.QUALIFICATION,
                    capacity.QUALIFICATION_PIN,
                    child_path,
                    work_root=scratch,
                )
                child = load_receipt(child_path)
                row = {
                    "step": step,
                    "exercise_seconds": time.monotonic() - start,
                    "receipt": child,
                    "receipt_payload_sha256": digest(child),
                    "receipt_file_sha256": file_sha(child_path),
                }
            else:
                row = run_step(step, bundle, qualification, scratch)
            validate_result(row, step, references)
            if (
                identity(
                    bundle, manifest_pin, root, test_evidence(unit_junit, fixture_junit, linux_ci)
                )
                != expected
            ):
                raise ValueError("Resilience source/input/machine changed during measurement.")
            progress["steps"].append(row)
            release.atomic(checkpoint, progress)
            print(json.dumps({"completed_step": step}), flush=True)
        release.qualification(capacity.QUALIFICATION, capacity.QUALIFICATION_PIN, bundle)
        if (
            identity(bundle, manifest_pin, root, test_evidence(unit_junit, fixture_junit, linux_ci))
            != expected
        ):
            raise ValueError("Resilience provenance changed before publication.")
        result = {
            "schema_version": 1,
            "verification": workload.POLICY["version"],
            "assessment_completed": True,
            "operational_passed": True,
            "deployment_eligible": False,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "identity": {k: v for k, v in expected.items() if k != "bundle_path"},
            "policy": workload.POLICY,
            "matrix": workload.CELLS,
            "steps": progress["steps"],
            "steady_load_targets_met": all(
                row["result"]["phases"][0]["summary"]["targets_met"]
                for row in progress["steps"]
                if row["step"] in {"sustained", "memory-pressure"}
            ),
            "limits": [
                "Constructed snapshot contexts and a finite local Linux matrix, not representative production traffic or a statistical SLO.",
                "Wire disconnect differs from controlled ASGI-task cancellation; fixture faults are separate from original-model lifecycle evidence.",
                "512MiB driver occupancy is bounded memory pressure, not actual OOM, CPU exhaustion or a remote dependency outage.",
                "Same-model A/B local control is not public routing, zero downtime, native-host or daemon/power-loss recovery.",
                "Preserved 2GiB RSS budget remains unmet; no model/quota/cache-default optimization or deployment authorization.",
            ],
        }
        publish(output, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--unit-junit", type=Path, required=True)
    parser.add_argument("--fixture-junit", type=Path, required=True)
    parser.add_argument("--linux-ci", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(
            args.bundle,
            args.manifest_sha256,
            args.output,
            args.work_root,
            unit_junit=args.unit_junit,
            fixture_junit=args.fixture_junit,
            linux_ci=args.linux_ci,
        )
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        parser.exit(1, "Resilience validation failed; inspect private journals/checkpoints/logs.\n")


if __name__ == "__main__":
    main()
