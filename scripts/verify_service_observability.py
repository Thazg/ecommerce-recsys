"""Verify bounded service metrics/logs and paired real HTTP reference parity."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from ecommerce_recsys.artifacts.contract import file_sha

if __package__:
    from scripts import verify_service_cache as cache_probe
else:
    import verify_service_cache as cache_probe

ROOT = cache_probe.ROOT
EXPECTED_COUNTERS = {"misses": 101, "hits": 109}


def parse_metrics(text):
    """Validate unique numeric samples and histogram invariants of this exporter."""
    if not text.endswith("\n"):
        raise ValueError("Metrics must end with a newline.")
    result, declarations = {}, {}
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split()
            if name in declarations:
                raise ValueError("Duplicate metric family declaration.")
            declarations[name] = kind
        elif not line.startswith("#"):
            match = re.fullmatch(r"([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? ([0-9.eE+\-]+)", line)
            if not match:
                raise ValueError("Invalid metric sample.")
            name, raw, value = match.groups()
            pairs = re.findall(r'(\w+)=("(?:\\.|[^"\\])*")', raw or "")
            if ",".join(f"{key}={value}" for key, value in pairs) != (raw or ""):
                raise ValueError("Invalid label syntax.")
            dimensions = tuple(sorted((key, json.loads(value)) for key, value in pairs))
            if len(dict(dimensions)) != len(dimensions):
                raise ValueError("Duplicate label.")
            key = name, dimensions
            if key in result or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("Duplicate, nonfinite or negative sample.")
            result[key] = float(value)
    for (name, dimensions), count in result.items():
        if name.endswith("_count"):
            family = name.removesuffix("_count")
            buckets = [
                (float(dict(labels)["le"]), value)
                for (metric, labels), value in result.items()
                if metric == family + "_bucket"
                and tuple((k, v) for k, v in labels if k != "le") == dimensions
            ]
            ordered = sorted(buckets)
            if (
                not ordered
                or ordered[-1] != (math.inf, count)
                or any(a[1] > b[1] for a, b in zip(ordered, ordered[1:]))
            ):
                raise ValueError("Histogram buckets do not reconcile.")
    if not declarations:
        raise ValueError("Missing metric families.")
    return result


def value(data, name, **labels):
    return sum(
        number
        for (metric, dimensions), number in data.items()
        if metric == name and all(dict(dimensions).get(key) == item for key, item in labels.items())
    )


class ObservedProbe(cache_probe.Probe):
    captures = []

    def call(self, method, path, *args, **kwargs):
        response, duration = super().call(method, path, *args, **kwargs)
        if path == "/health/ready" and response.get("primary_calls", 0) > 0:
            self.connection.request("GET", "/metrics")
            metrics = self.connection.getresponse()
            raw = metrics.read()
            if (
                metrics.status != 200
                or metrics.getheader("Content-Type") != "text/plain; version=0.0.4; charset=utf-8"
            ):
                raise ValueError("Metrics endpoint contract differs.")
            data = parse_metrics(raw.decode("utf-8"))
            if (
                value(data, "recsys_primary_calls_total") != response["primary_calls"]
                or value(data, "recsys_ready") != 1
                or value(data, "recsys_primary_in_flight") != 0
            ):
                raise ValueError("Worker/readiness telemetry differs from service state.")
            if (
                value(data, "recsys_primary_duration_seconds_count", outcome="success")
                != response["primary_calls"]
            ):
                raise ValueError("Worker duration count differs.")
            if (
                value(data, "recsys_observer_errors_total") != 0
                or value(data, "recsys_memory_sample_success") != 1
            ):
                raise ValueError("Observer or memory sampling failed.")
            for event in ("hits", "misses"):
                if (
                    value(data, "recsys_cache_events_total", event=event)
                    != response["cache"][event]
                ):
                    raise ValueError("Cache events differ from service counters.")
            self.captures.append(
                {
                    "enabled": response["cache"]["enabled"],
                    "metrics": raw.decode("utf-8"),
                    "series": len(data),
                }
            )
        return response, duration


def verify(bundle, pin):
    source = {
        **cache_probe.code_identity(),
        "scripts/verify_service_observability.py": file_sha(Path(__file__)),
    }
    ObservedProbe.captures = []
    original = cache_probe.Probe
    cache_probe.Probe = ObservedProbe
    try:
        receipt = cache_probe.verify(bundle, pin)
    finally:
        cache_probe.Probe = original
    if source != {
        **cache_probe.code_identity(),
        "scripts/verify_service_observability.py": file_sha(Path(__file__)),
    }:
        raise ValueError("Measured implementation changed.")
    receipt["identity"]["files_sha256"] = source
    validations = []
    for enabled, filename in ((False, "cache_http_off.log"), (True, "cache_http_on.log")):
        capture = [row for row in ObservedProbe.captures if row["enabled"] == enabled][-1]
        data = parse_metrics(capture["metrics"])
        requests = (
            215 if enabled else 106
        )  # References/prefix/cold, ready checks, schema; scrapes excluded.
        if value(data, "recsys_http_requests_total") != requests:
            raise ValueError(
                f"HTTP observation count differs: {value(data, 'recsys_http_requests_total')} != {requests}."
            )
        deliveries = 210 if enabled else 102
        if value(data, "recsys_deliveries_total") != deliveries:
            raise ValueError("Successful delivery count differs.")
        if value(data, "recsys_model_info", manifest_sha256=pin) != 1:
            raise ValueError("Model telemetry identity differs.")
        if enabled and any(
            value(data, "recsys_cache_events_total", event=event) != expected
            for event, expected in EXPECTED_COUNTERS.items()
        ):
            raise ValueError("Final cache events differ.")
        records = [
            json.loads(line)
            for line in (ROOT / ".local" / filename).read_text(encoding="utf-8").splitlines()
            if line.startswith('{"event":')
        ]
        http = [row for row in records if row["event"] == "http_request"]
        # Log captures occur after the last scrape; include any completed health calls.
        if len(http) != requests:
            raise ValueError("Structured HTTP logs do not reconcile with metrics.")
        serialized = json.dumps(records)
        if any(
            token in serialized
            for token in ("cache-probe-unknown-user", "user_id", '"items"', "traceback")
        ):
            raise ValueError("Owned logs contain private fields.")
        validations.append(
            {
                "cache_enabled": enabled,
                "sample_series": capture["series"],
                "http_requests": requests,
                "deliveries": deliveries,
                "owned_json_records": len(records),
                "metrics_text": capture["metrics"],
                "owned_log_events_sha256": cache_probe.digest(records),
                "all_passed": True,
            }
        )
    receipt["observability"] = {
        "phases": validations,
        "all_passed": True,
        "scope": "Real normal-path telemetry; forced failure/cancellation/redaction paths use deterministic tests. ASGI histogram and client timings have different boundaries.",
    }
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve completed receipts; choose a new output path.")
    try:
        receipt = verify(args.bundle, args.manifest_sha256)
        cache_probe.publish_receipt(args.output, receipt)
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        parser.exit(1, f"Observability verification failed: {error}\n")
    print(
        json.dumps(
            {
                "parity": receipt["parity"],
                "gates": receipt["benefit_gates"],
                "telemetry": [
                    {k: v for k, v in phase.items() if k != "metrics_text"}
                    for phase in receipt["observability"]["phases"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
