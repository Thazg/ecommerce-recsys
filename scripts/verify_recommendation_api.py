"""Verify a real loopback HTTP process against sealed snapshot references."""

from __future__ import annotations

import argparse
import http.client
import importlib.metadata
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from ecommerce_recsys.artifacts.contract import digest, file_sha, runtime_code, write_json
from ecommerce_recsys.evaluation.latency import latency_metrics
from ecommerce_recsys.serving.contracts import (
    ModelIdentity,
    RecommendationRequest,
    RecommendationResponse,
    ServiceSettings,
)

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_FILES = (
    *sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src/ecommerce_recsys/serving").glob("*.py")
    ),
    "scripts/verify_recommendation_api.py",
    "requirements/serving.txt",
    "requirements/serving-test.txt",
    "src/ecommerce_recsys/evaluation/latency.py",
)


def implementation_identity():
    return {name: file_sha(ROOT / name) for name in IDENTITY_FILES}


def reference_inputs(bundle: Path, manifest_sha256: str):
    # Verify pins before parsing. The server independently verifies every component.
    try:
        if file_sha(bundle / "model_manifest.json") != manifest_sha256:
            raise ValueError("Manifest pin differs.")
        manifest = json.loads((bundle / "model_manifest.json").read_text(encoding="utf-8"))
        reference_sha = file_sha(bundle / "references.json")
    except (OSError, UnicodeError, RecursionError) as error:
        raise ValueError("Cannot read valid manifest/reference files.") from error
    except json.JSONDecodeError as error:
        raise ValueError("Manifest/reference file is not valid JSON.") from error
    try:
        identity = ModelIdentity(
            bundle_version=manifest["bundle_version"], cutoff=manifest["snapshot"]["cutoff"]
        )
        recorded_sha = manifest["components"]["references.json"]["sha256"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Malformed snapshot manifest contract.") from error
    if reference_sha != recorded_sha:
        raise ValueError("Reference component differs from the sealed manifest.")
    try:
        references = json.loads((bundle / "references.json").read_text(encoding="utf-8"))
        if not isinstance(references, list) or not references:
            raise ValueError("References must be a nonempty list.")
        routes, users = set(), set()
        for row in references:
            request = RecommendationRequest(user_id=row["user_id"])
            response = RecommendationResponse(
                request_id="reference",
                **identity.model_dump(),
                route=row["trace"]["route"],
                items=row["trace"]["output"],
            )
            if request.user_id in users or (
                response.route == "hybrid_learned" and request.user_id is None
            ):
                raise ValueError("Duplicate or invalid reference context.")
            routes.add(response.route)
            users.add(request.user_id)
        if routes != {"hybrid_learned", "recent_popularity"}:
            raise ValueError("References require warm and cold contexts.")
    except (OSError, RecursionError, KeyError, TypeError, ValueError) as error:
        raise ValueError("Malformed warm/cold producer reference contract.") from error
    return manifest, references, reference_sha


class Probe:
    def __init__(self, port):
        self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        self.request_ids = set()

    def call(self, method, path, body=None, media="application/json", expected=200):
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        started = time.perf_counter()
        self.connection.request(method, path, body=body, headers={"Content-Type": media})
        response = self.connection.getresponse()
        raw = response.read()
        elapsed = time.perf_counter() - started
        if response.status != expected:
            raise ValueError(
                f"HTTP status differs for {method} {path}: expected {expected}, received {response.status}."
            )
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ValueError(f"Invalid JSON response for {method} {path}.") from error
        if not isinstance(value, dict):
            raise ValueError(f"Expected a JSON object for {method} {path}.")
        request_id = response.getheader("X-Request-ID")
        if (
            not re.fullmatch("[0-9a-f]{32}", request_id or "")
            or request_id in self.request_ids
            or (path != "/openapi.json" and value.get("request_id") != request_id)
        ):
            raise ValueError(f"HTTP contract failed for {method} {path}: {response.status}.")
        self.request_ids.add(request_id)
        return value, elapsed

    def close(self):
        self.connection.close()


def compare_output(actual, reference, manifest, k):
    expected = {
        "items": reference["trace"]["output"][:k],
        "route": reference["trace"]["route"],
        "bundle_version": manifest["bundle_version"],
        "cutoff": manifest["snapshot"]["cutoff"],
    }
    if {key: value for key, value in actual.items() if key != "request_id"} != expected:
        raise ValueError("HTTP prediction differs from the sealed reference.")
    return expected


def verify_openapi(schema):
    try:
        contract = schema["components"]["schemas"]["RecommendationRequest"]
        responses = schema["paths"]["/v1/recommendations"]["post"]["responses"]
        if (
            contract.get("additionalProperties") is not False
            or contract["properties"]["k"].get("maximum") != 20
            or not {"404", "405", "503"}.issubset(responses)
        ):
            raise ValueError("Request or response contract differs.")
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("OpenAPI does not expose the strict HTTP contract.") from error


def publish_receipt(path: Path, receipt):
    if path.exists():
        raise ValueError("Preserve completed receipts; select a new output path.")
    receipt = {**receipt, "content_sha256": digest(receipt)}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, receipt)


def verify(bundle: Path, manifest_sha256: str, *, startup_timeout=180):
    ServiceSettings(bundle, manifest_sha256)
    manifest, references, reference_sha = reference_inputs(bundle, manifest_sha256)
    source = implementation_identity()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    scratch = ROOT / ".local"
    scratch.mkdir(exist_ok=True)
    log_path = scratch / "recommendation_api_probe.log"
    command = [
        sys.executable,
        "-m",
        "ecommerce_recsys.serving",
        "--bundle-path",
        str(bundle.resolve()),
        "--manifest-sha256",
        manifest_sha256,
        "--port",
        str(port),
    ]
    samples = []
    stop_sampling = threading.Event()
    started = time.perf_counter()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        child = psutil.Process(process.pid)

        def sample_memory():
            while not stop_sampling.is_set():
                try:
                    samples.append(child.memory_info().rss)
                except psutil.Error:
                    return
                stop_sampling.wait(0.05)

        sampler = threading.Thread(target=sample_memory, daemon=True)
        sampler.start()
        probe = Probe(port)
        try:
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"API startup failed; inspect {log_path}.")
                if time.perf_counter() - started > startup_timeout:
                    raise TimeoutError("API startup deadline exceeded.")
                try:
                    ready, _ = probe.call("GET", "/health/ready")
                    break
                except OSError:
                    probe.close()
                    probe = Probe(port)
                    time.sleep(0.2)
            startup_seconds = time.perf_counter() - started
            ready_rss = child.memory_info().rss
            if (
                ready.get("bundle_version") != manifest["bundle_version"]
                or ready.get("cutoff") != manifest["snapshot"]["cutoff"]
            ):
                raise ValueError("Readiness reports a different snapshot.")
            probe.call("GET", "/health/live")
            schema, _ = probe.call("GET", "/openapi.json")
            verify_openapi(schema)
            warm = [row for row in references if row["trace"]["route"] == "hybrid_learned"]
            cold = next(row for row in references if row["trace"]["route"] == "recent_popularity")
            # One excluded warm-up, followed by one sequential pass over all references.
            probe.call("POST", "/v1/recommendations", {"user_id": warm[0]["user_id"]})
            timings = {"hybrid_learned": [], "recent_popularity": []}
            outputs = []
            for row in references:
                result, elapsed = probe.call(
                    "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": 20}
                )
                outputs.append(compare_output(result, row, manifest, 20))
                timings[row["trace"]["route"]].append(elapsed)
            for row in warm[:3]:
                for k in (5, 10):
                    result, _ = probe.call(
                        "POST", "/v1/recommendations", {"user_id": row["user_id"], "k": k}
                    )
                    compare_output(result, row, manifest, k)
            unknown = "http-probe-unknown-user"
            # Training IDs are decimal Retailrocket identifiers; this synthetic ID is cold.
            result, _ = probe.call("POST", "/v1/recommendations", {"user_id": unknown})
            compare_output(result, cold, manifest, 20)
            checks = [
                ({"k": True}, "application/json", 422, "validation_error"),
                ({"k": 1.0}, "application/json", 422, "validation_error"),
                ({"history": ["private-input"]}, "application/json", 422, "validation_error"),
                (b'{"k":1,"k":2}', "application/json", 400, "invalid_json"),
                (b'{"k":NaN}', "application/json", 400, "invalid_json"),
                (b"{}", "text/plain", 415, "unsupported_media_type"),
                (b" " * 8193, "application/json", 413, "body_too_large"),
            ]
            for body, media, status, code in checks:
                result, _ = probe.call("POST", "/v1/recommendations", body, media, status)
                if result["error"]["code"] != code or "private-input" in json.dumps(result):
                    raise ValueError("HTTP error contract or redaction differs.")
            probe.call("GET", "/health/ready")
            final_rss = child.memory_info().rss
        finally:
            probe.close()
            # This disposable verifier terminates its child; graceful drain is unit-tested.
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            stop_sampling.set()
            sampler.join(timeout=2)
    if source != implementation_identity():
        raise ValueError("API source changed during verification.")
    return {
        "schema_version": 1,
        "verification": "loopback snapshot reference-output parity; no future-label scoring",
        "identity": {
            "bundle_version": manifest["bundle_version"],
            "manifest_sha256": manifest_sha256,
            "references_sha256": reference_sha,
            "reader_runtime_code_sha256": runtime_code(),
            "api_files_sha256": source,
            "openapi_sha256": digest(schema),
        },
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("fastapi", "starlette", "uvicorn", "pydantic", "anyio", "psutil")
            },
        },
        "parity": {
            "warm_references": len(warm),
            "cold_references": len(references) - len(warm),
            "prefix_checks": len(warm[:3]) * 2,
            "unknown_user_checks": 1,
            "error_contract_checks": len(checks),
            "all_passed": True,
            "ordered_outputs_sha256": digest(outputs),
        },
        "timing": {
            "scope": "sequential loopback HTTP over one persistent connection; warm-up excluded; includes transport and JSON response read; no concurrent load or SLA inference",
            "startup_scope": "child launch through manifest/component verification, model restoration, two startup predictions and first HTTP readiness response",
            "startup_seconds": startup_seconds,
            "warm": latency_metrics(timings["hybrid_learned"]),
            "cold": latency_metrics(timings["recent_popularity"]),
        },
        "memory": {
            "scope": "server process RSS only; 50ms sampling; sampled peak is a lower bound on true peak",
            "ready_rss_bytes": ready_rss,
            "after_requests_rss_bytes": final_rss,
            "sampled_peak_rss_bytes": max(samples + [ready_rss, final_rss]),
            "charter_target_bytes": 2 * 1024**3,
            "observed_samples_within_target": max(samples + [ready_rss, final_rss]) <= 2 * 1024**3,
        },
        "limits": [
            "Historical snapshot; no dynamic request history, public deployment or Linux bundle parity.",
            "Reference sample verifies HTTP outputs, not full-fold quality or a concurrent-load SLO.",
            "One cold reference cannot establish a cold latency distribution.",
            "Probe cleanup terminates the disposable process; graceful drain is covered by deterministic unit tests.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Receipt already exists; preserve it and use a new output path.")
    try:
        record = verify(args.bundle, args.manifest_sha256)
        publish_receipt(args.output, record)
    except (ValueError, RuntimeError, TimeoutError, OSError) as error:
        parser.exit(1, f"HTTP verification failed: {error}\n")
    print(json.dumps({key: record[key] for key in ("parity", "timing", "memory")}, indent=2))


if __name__ == "__main__":
    main()
