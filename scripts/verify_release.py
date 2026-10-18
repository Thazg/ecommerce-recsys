"""Run source-pinned functional integration gates without training Retailrocket models."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import (
    digest,
    environment,
    file_sha,
    verify_inventory,
    write_json,
)

if __package__:
    from scripts.release_validation import (
        POLICY,
        QUALITY_PATH,
        QUALITY_PIN,
        ROOT,
        junit_summary,
        load_receipt,
        source_identity,
        validate_http,
        validate_loader,
        validate_quality,
    )
    from scripts.verify_recommendation_api import reference_inputs
else:
    from release_validation import (
        POLICY,
        QUALITY_PATH,
        QUALITY_PIN,
        ROOT,
        junit_summary,
        load_receipt,
        source_identity,
        validate_http,
        validate_loader,
        validate_quality,
    )
    from verify_recommendation_api import reference_inputs


def command_environment():
    env = os.environ.copy()
    for name in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "RECSYS_API_TOKEN",
        "RECSYS_API_TOKEN_FILE",
        "RECSYS_BUNDLE_PATH",
        "RECSYS_MANIFEST_SHA256",
    ):
        env.pop(name, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def run_command(arguments, *, log_path, timeout):
    started = time.monotonic()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=command_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        descendants = {}
        stopped = threading.Event()

        def observe_children():
            while not stopped.is_set():
                try:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        descendants[(child.pid, child.create_time())] = child
                except psutil.Error:
                    pass
                stopped.wait(0.05)

        observer = threading.Thread(target=observe_children, daemon=True)
        observer.start()
        try:
            process.wait(timeout=timeout)
        finally:
            stopped.set()
            observer.join(5)
            try:
                for child in psutil.Process(process.pid).children(recursive=True):
                    descendants[(child.pid, child.create_time())] = child
            except psutil.Error:
                pass
            remaining = []
            for child in descendants.values():
                try:
                    if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                        child.terminate()
                        remaining.append(child)
                except psutil.Error:
                    pass
            if process.poll() is None:
                process.terminate()
            _, alive = psutil.wait_procs(remaining, timeout=5)
            for child in alive:
                try:
                    child.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(alive, timeout=5)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    if process.returncode != 0 or remaining:
        raise ValueError("A required integration gate failed; inspect private logs.")
    return time.monotonic() - started


def publish(path, record):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ValueError("Preserve completed receipts; choose a new output path.")
    record = {**record, "content_sha256": digest(record)}
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging = tempfile.mkstemp(prefix=".integration-", suffix=".json", dir=path.parent)
    os.close(descriptor)
    staging = Path(staging)
    try:
        write_json(staging, record)
        # A same-filesystem hard link publishes complete bytes only if absent.
        # No replace fallback may overwrite another successful gate's receipt.
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def verify(bundle, pin, *, quality=QUALITY_PATH, quality_pin=QUALITY_PIN):
    bundle, quality = Path(bundle).resolve(), Path(quality).resolve()
    if not re.fullmatch("[0-9a-f]{64}", pin or ""):
        raise ValueError("Provide a trusted lowercase manifest SHA-256.")
    source = source_identity()
    runtime = environment()
    manifest = verify_inventory(bundle, pin)
    validate_quality(quality, quality_pin, manifest, pin)
    _, references, reference_pin = reference_inputs(bundle, pin)
    if (
        len(references) != 101
        or sum(row["trace"]["route"] == "hybrid_learned" for row in references) != 100
    ):
        raise ValueError(
            "The real integration profile requires 100 warm and one cold sealed references."
        )
    scratch_parent = ROOT / ".local"
    scratch_parent.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="release-verification-", dir=scratch_parent))
    started = datetime.now(timezone.utc).isoformat()
    checks = []
    for name, command in (
        ("dependencies", ["-m", "pip", "check"]),
        (
            "http_dependencies",
            ["-c", "import fastapi,uvicorn,h11,httpx2; from fastapi.testclient import TestClient"],
        ),
        ("lint", ["-m", "ruff", "check", "."]),
        ("format", ["-m", "ruff", "format", "--check", "."]),
    ):
        seconds = run_command(command, log_path=scratch / f"{name}.log", timeout=120)
        checks.append({"gate": name, "command": command, "seconds": seconds, "passed": True})
    profiles = []
    for name, selection in (
        ("unit", ["tests/unit"]),
        ("fixture", ["tests/integration", "-m", "not real_bundle"]),
        (
            "real_bundle",
            [
                "tests/integration",
                "-m",
                "real_bundle",
                "--run-real-bundle",
                "--bundle-path",
                str(bundle),
                "--bundle-manifest-sha256",
                pin,
                "--bundle-quality-receipt",
                str(quality),
                "--bundle-quality-sha256",
                quality_pin,
                "--bundle-loader-evidence",
                str(scratch / "loader.json"),
            ],
        ),
    ):
        report = scratch / f"{name}.xml"
        command = [
            "-m",
            "pytest",
            *selection,
            "-q",
            "-o",
            "xfail_strict=true",
            "--basetemp",
            str(scratch / f"pytest-{name}"),
            "--junitxml",
            str(report),
        ]
        seconds = run_command(command, log_path=scratch / f"{name}.log", timeout=600)
        summary = junit_summary(report, profile=name)
        if summary["passed"] < {"unit": 699, "fixture": 7, "real_bundle": 1}[name]:
            raise ValueError("Required profile contains too few successful cases.")
        profiles.append(
            {
                **summary,
                "seconds": seconds,
                "junit_sha256": file_sha(report),
                "command": "pytest "
                + {
                    "unit": "tests/unit",
                    "fixture": "tests/integration -m 'not real_bundle'",
                    "real_bundle": "tests/integration -m real_bundle --run-real-bundle --bundle-path <bundle> --bundle-manifest-sha256 <trusted pin> --bundle-quality-receipt <quality> --bundle-quality-sha256 <trusted pin>",
                }[name],
            }
        )
    loader = load_receipt(scratch / "loader.json", checksum="payload_sha256")
    validate_loader(loader, manifest=manifest, pin=pin, quality_pin=quality_pin)
    http_path = scratch / "http.json"
    http_seconds = run_command(
        [
            str(ROOT / "scripts/verify_service_hardening.py"),
            "--bundle",
            str(bundle),
            "--manifest-sha256",
            pin,
            "--output",
            str(http_path),
        ],
        log_path=scratch / "http.log",
        timeout=600,
    )
    http = load_receipt(http_path)
    assertions = validate_http(http, manifest=manifest, pin=pin, references=references)
    if source != source_identity() or environment() != runtime or file_sha(quality) != quality_pin:
        raise ValueError("Source or trusted inputs changed during integration verification.")
    verify_inventory(bundle, pin)
    # Preserve complete freshly measured HTTP evidence inside this receipt. The
    # standalone producer/reference and previous public receipts are unchanged.
    return {
        "schema_version": 1,
        "verification": POLICY["verification"],
        "policy": POLICY,
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "files_sha256": source,
            "manifest_sha256": pin,
            "quality_receipt_sha256": quality_pin,
            "references_sha256": reference_pin,
            "bundle_version": manifest["bundle_version"],
            "snapshot_cutoff": manifest["snapshot"]["cutoff"],
        },
        "runtime": runtime,
        "static_checks": checks,
        "test_profiles": profiles,
        "http_seconds": http_seconds,
        "loader_evidence": loader,
        "http_evidence": http,
        "functional_assertions": assertions,
        "functional_passed": True,
        "deployment_eligible": False,
        "deployment_gates": {
            "linux_full_bundle": "unverified",
            "representative_load": "unverified",
            "target_host_recovery": "unverified",
            "sampled_rss_within_2gib": all(
                http[name]["memory"]["observed_samples_within_target"]
                for name in ("cache_off_anonymous", "cache_on_bearer")
            ),
        },
        "limits": [
            "No new recommendation-quality or blind-validation evidence.",
            "Fixture integration trains only synthetic models; real model/quality artifacts are read-only.",
            "Windows process stop/restart uses termination; POSIX SIGTERM cleanup and unit-controlled owned drain have separate scopes.",
            "Functional success does not permit public deployment or waive RSS/workload/Linux gates.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--quality-receipt", type=Path, default=QUALITY_PATH)
    parser.add_argument("--quality-sha256", default=QUALITY_PIN)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Preserve completed receipts; choose a new output path.")
    try:
        record = verify(
            args.bundle,
            args.manifest_sha256,
            quality=args.quality_receipt,
            quality_pin=args.quality_sha256,
        )
        publish(args.output, record)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(
            1,
            "Functional integration gate failed; no successful receipt published. Inspect private release logs.\n",
        )
    print(
        json.dumps(
            {
                "functional_passed": True,
                "deployment_eligible": False,
                "output": args.output.as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
