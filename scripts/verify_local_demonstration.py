"""Check an owned indexed-reader HTTP process against the sealed references."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import digest, environment, file_sha, verify_inventory

if __package__:
    from scripts.profile_snapshot_memory import publish, sources, validate_output_path
    from scripts.verify_recommendation_api import reference_inputs
    from scripts.verify_service_cache import check_response
    from scripts.verify_service_hardening import HardeningProbe
else:
    from profile_snapshot_memory import publish, sources, validate_output_path
    from verify_recommendation_api import reference_inputs
    from verify_service_cache import check_response
    from verify_service_hardening import HardeningProbe

ROOT = Path(__file__).resolve().parents[1]
POLICY = {
    "host": "127.0.0.1",
    "warm_references": 100,
    "cold_references": 1,
    "prefix_checks": 6,
    "denial_checks": 8,
    "startup_deadline_seconds": 120,
    "overall_deadline_seconds": 300,
    "cache": "disabled",
    "busy_policy": "reject",
    "authentication": "ephemeral probe credential; never persisted",
    "stop_scope": "owned process termination; graceful drain not inferred",
}


def identity():
    names = (
        "scripts/serve_local_snapshot.py",
        "scripts/verify_local_demonstration.py",
        "scripts/verify_recommendation_api.py",
        "scripts/verify_service_cache.py",
        "scripts/verify_service_observability.py",
        "scripts/verify_service_hardening.py",
        "tests/unit/test_local_demonstration.py",
        "requirements/serving.txt",
        "requirements/serving-test.txt",
    )
    return {
        **sources(),
        **{name: file_sha(ROOT / name) for name in names},
    }


def stop_owned(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
    else:
        child.wait(timeout=10)


def verify(bundle, pin):
    manifest, references, reference_sha = reference_inputs(bundle, pin)
    if (
        len(references) != 101
        or sum(row["trace"]["route"] == "hybrid_learned" for row in references) != 100
        or sum(row["user_id"] is None for row in references) != 1
    ):
        raise ValueError("The complete sealed 100-warm/one-cold sample is required.")
    verify_inventory(bundle, pin)
    before = identity()
    with socket.socket() as reservation:
        reservation.bind((POLICY["host"], 0))
        port = reservation.getsockname()[1]
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "RECSYS_API_TOKEN": token}
    env.pop("RECSYS_API_TOKEN_FILE", None)
    command = [
        sys.executable,
        "-m",
        "scripts.serve_local_snapshot",
        "--bundle-path",
        str(bundle.resolve()),
        "--manifest-sha256",
        pin,
        "--port",
        str(port),
    ]
    scratch = ROOT / ".local"
    scratch.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="local-demo-http-", suffix=".log", dir=scratch)
    started = time.monotonic()
    outputs = []
    probe = HardeningProbe(port, token=token)
    with os.fdopen(fd, "wb") as log:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            while True:
                if child.poll() is not None:
                    raise ValueError("Owned local demonstration exited before readiness.")
                if time.monotonic() - started > POLICY["startup_deadline_seconds"]:
                    raise TimeoutError("Local demonstration startup deadline exceeded.")
                try:
                    probe.call("GET", "/health/ready")
                    break
                except OSError:
                    time.sleep(0.1)
            listeners = psutil.Process(child.pid).net_connections(kind="tcp")
            if not any(
                connection.status == psutil.CONN_LISTEN
                and connection.laddr.ip == POLICY["host"]
                and connection.laddr.port == port
                for connection in listeners
            ):
                raise ValueError("Ready listener does not belong to the owned child.")
            startup_seconds = time.monotonic() - started
            for row in references:
                if time.monotonic() - started > POLICY["overall_deadline_seconds"]:
                    raise TimeoutError("Local verification deadline exceeded.")
                response, _ = probe.call(
                    "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": 20}
                )
                outputs.append(check_response(response, row, manifest, pin, 20, "disabled"))
            warm = next(row for row in references if row["trace"]["route"] == "hybrid_learned")
            cold = next(row for row in references if row["user_id"] is None)
            for row in (warm, cold):
                for k in (5, 10, 20):
                    response, _ = probe.call(
                        "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
                    )
                    check_response(response, row, manifest, pin, k, "disabled")
            for body in ({"k": 0}, {"k": 21}, {"k": True}, {"history": ["private"]}):
                probe.call("POST", "/v1/recommendations", body, expected=422)
            probe.call("GET", "/health/ready", credential=False, expected=401)
            probe.call("POST", "/v1/recommendations", {}, credential=False, expected=401)
            probe.call(
                "POST", "/v1/recommendations", {}, headers={"Host": "foreign.invalid"}, expected=400
            )
            probe.call("POST", "/v1/recommendations", {}, headers={"Origin": "null"}, expected=403)
            probe.call("GET", "/health/ready")
            if child.poll() is not None:
                raise ValueError("Owned service exited before verification completed.")
        finally:
            stop_owned(child)
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex((POLICY["host"], port)) == 0:
            raise ValueError("Local demonstration listener remains after owned stop.")
    if before != identity():
        raise ValueError("Source changed during local demonstration verification.")
    result = {
        "schema_version": 1,
        "verification": "local-snapshot-demonstration-v1",
        "policy": POLICY,
        "sources_sha256": before,
        "manifest_sha256": pin,
        "references_sha256": reference_sha,
        "reference_outputs_sha256": digest(outputs),
        "runtime": environment(),
        "startup_seconds": startup_seconds,
        "warm_references": 100,
        "cold_references": 1,
        "prefix_checks": 6,
        "denial_checks": 8,
        "http_deliveries": probe.deliveries,
        "parity_passed": True,
        "owned_process_exited": True,
        "listener_closed": True,
        "child_exit_code": child.returncode,
        "graceful_drain_measured": False,
        "rss_measured": False,
        "public_inference": False,
        "cloud_deployed": False,
        "deployment_eligible": False,
    }
    return {**result, "content_sha256": digest(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_output_path(args.output)
        if args.output.exists():
            raise ValueError("Preserve existing local verification records.")
        result = verify(args.bundle, args.manifest_sha256)
        publish(args.output, result)
    except (ValueError, OSError, RuntimeError, TimeoutError):
        parser.exit(2, "Local verification failed; inspect private logs.\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "parity_passed",
                    "warm_references",
                    "cold_references",
                    "owned_process_exited",
                    "public_inference",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
