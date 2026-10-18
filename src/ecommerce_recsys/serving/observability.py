"""Fixed-schema local telemetry; no request payloads or unbounded sample storage."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from functools import wraps
from threading import Lock
from time import time

import psutil

EVENT_LOGGER = logging.getLogger("ecommerce_recsys.serving.events")
BOUNDS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0)
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
ENDPOINTS = {
    "/v1/recommendations": "recommendations",
    "/health/live": "live",
    "/health/ready": "ready",
    "/openapi.json": "openapi",
    "/docs": "docs",
    "/docs/oauth2-redirect": "docs",
    "/redoc": "docs",
    "/metrics": "metrics",
}
METHODS = {"GET", "POST", "HEAD", "OPTIONS"}
STATUSES = {"200", "400", "404", "405", "413", "415", "422", "500", "503"}
OUTCOMES = {"completed", "cancelled", "disconnected", "aborted"}
ROUTES = {"hybrid_learned", "recent_popularity", "recent_popularity_fallback"}
CACHE_PATHS = {"disabled", "miss", "hit", "bypass"}
CACHE_EVENTS = {"hits", "misses", "evictions", "expirations", "oversized"}
ERROR_CODES = {
    "invalid_json",
    "invalid_request",
    "body_too_large",
    "unsupported_media_type",
    "validation_error",
    "http_error",
    "internal_error",
    "inference_failed",
    "busy",
    "not_ready",
}
EVENTS = {
    "startup_ready",
    "startup_failed",
    "startup_cancelled",
    "startup_stopped",
    "cleanup_complete",
    "cache_disabled",
    "primary_failed",
    "fallback_failed",
    "submission_failed",
}


class EventStreamHandler(logging.StreamHandler):
    def handleError(self, record):
        # StreamHandler normally swallows I/O errors; let the guarded observer
        # count them without logging a traceback or recursively using this sink.
        raise OSError("Owned event sink is unavailable.") from None


def configure_event_logging():
    """Only the supported launcher installs the owned JSON stream handler."""
    handler = EventStreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    EVENT_LOGGER.handlers[:] = [handler]
    EVENT_LOGGER.setLevel(logging.INFO)
    EVENT_LOGGER.propagate = False


def guarded(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            with self._lock:
                self._errors += 1
            return None

    return invoke


def labels(values):
    def escaped(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    return (
        "{" + ",".join(f'{key}="{escaped(value)}"' for key, value in values) + "}" if values else ""
    )


class Telemetry:
    """One immutable-model app registry; every event dimension is allowlisted."""

    def __init__(self, *, rss_reader=None):
        self._lock = Lock()
        self._counts = Counter()
        self._histograms = {}
        self._errors = 0
        self._active = 0
        self._startup = None
        self._model = None
        self._rss = rss_reader or (lambda: psutil.Process().memory_info().rss)

    def _inc(self, name, dimensions=()):
        with self._lock:
            self._counts[name, dimensions] += 1

    def _observe(self, name, dimensions, duration):
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Telemetry duration must be finite and nonnegative.")
        with self._lock:
            row = self._histograms.setdefault((name, dimensions), [0, 0.0, [0] * len(BOUNDS)])
            row[0] += 1
            row[1] += duration
            for index, bound in enumerate(BOUNDS):
                row[2][index] += duration <= bound

    def _log(self, event, **fields):
        # Callers only supply fields built here, never arbitrary request/model objects.
        with self._lock:
            model = self._model
        EVENT_LOGGER.info(
            json.dumps(
                {
                    "event": event,
                    "timestamp_unix_seconds": time(),
                    "bundle_version": model[0] if model else None,
                    **fields,
                },
                ensure_ascii=True,
                allow_nan=False,
            )
        )

    @guarded
    def bind_model(self, version, manifest):
        if (
            type(version) is not str
            or not 1 <= len(version) <= 80
            or not re.fullmatch("[0-9a-f]{64}", manifest)
        ):
            raise ValueError("Invalid observed model identity.")
        with self._lock:
            self._model = (version, manifest)

    @guarded
    def clear_model(self):
        with self._lock:
            self._model = None

    @guarded
    def event(self, event, *, duration=None, request_id=None):
        if event not in EVENTS:
            raise ValueError("Unknown service event.")
        if duration is not None:
            if not math.isfinite(duration) or duration < 0:
                raise ValueError("Invalid startup duration.")
            with self._lock:
                self._startup = duration
        self._inc("recsys_lifecycle_events_total", (("event", event),))
        fields = {}
        if isinstance(request_id, str) and re.fullmatch("[0-9a-f]{32}", request_id):
            fields["request_id"] = request_id
        self._log(event, **fields)

    @guarded
    def cache_event(self, event):
        if event not in CACHE_EVENTS:
            raise ValueError("Unknown cache event.")
        self._inc("recsys_cache_events_total", (("event", event),))

    @guarded
    def admission(self, decision):
        if decision not in {"accepted", "busy_rejected", "busy_fallback", "not_ready"}:
            raise ValueError("Unknown admission decision.")
        self._inc("recsys_admission_total", (("decision", decision),))

    @guarded
    def primary_started(self):
        with self._lock:
            self._active += 1
        self._inc("recsys_primary_calls_total")

    @guarded
    def primary_finished(self, outcome, duration):
        if outcome not in {"success", "failed", "invalidated"}:
            raise ValueError("Unknown primary outcome.")
        with self._lock:
            self._active -= 1
        self._observe("recsys_primary_duration_seconds", (("outcome", outcome),), duration)

    @guarded
    def http(self, scope, status, outcome, duration):
        endpoint = ENDPOINTS.get(scope["path"], "other")
        if endpoint == "metrics":
            return
        if outcome not in OUTCOMES:
            raise ValueError("Unknown HTTP outcome.")
        method = scope["method"] if scope["method"] in METHODS else "other"
        status = str(status) if str(status) in STATUSES else "other"
        dimensions = (
            ("endpoint", endpoint),
            ("method", method),
            ("status", status),
            ("outcome", outcome),
        )
        self._inc("recsys_http_requests_total", dimensions)
        self._observe(
            "recsys_http_duration_seconds", (("endpoint", endpoint), ("outcome", outcome)), duration
        )
        state = scope.get("state", {})
        error = state.get("telemetry_error")
        if error in ERROR_CODES:
            self._inc("recsys_http_errors_total", (("code", error),))
        fields = dict(dimensions)
        if error in ERROR_CODES:
            fields["error_code"] = error
        request_id = state.get("request_id")
        if isinstance(request_id, str) and re.fullmatch("[0-9a-f]{32}", request_id):
            fields["request_id"] = request_id
        fields["duration_seconds"] = duration
        delivery = state.get("telemetry_delivery")
        if outcome == "completed" and status == "200" and delivery:
            route, cache, degraded = delivery
            if route not in ROUTES or cache not in CACHE_PATHS or type(degraded) is not bool:
                raise ValueError("Invalid delivery observation.")
            served = (("route", route), ("cache", cache), ("degraded", str(degraded).lower()))
            self._inc("recsys_deliveries_total", served)
            self._observe("recsys_delivery_duration_seconds", served, duration)
            fields.update(dict(served))
            fields["degraded"] = degraded
        self._log("http_request", **fields)

    @guarded
    def render(self, service):
        state, healthy = service.readiness()
        gauges = {
            "recsys_ready": int(healthy),
            "recsys_cache_enabled": int(service.cache is not None),
            "recsys_cache_failures": service.cache_failures,
            "recsys_cache_max_entries": service.settings.cache_max_entries,
            "recsys_cache_max_charged_bytes": service.settings.cache_max_bytes,
            "recsys_cache_ttl_seconds": service.settings.cache_ttl_seconds,
        }
        cache = service.cache
        try:
            snapshot = cache.snapshot() if cache is not None else {"entries": 0, "charged_bytes": 0}
            limits = {
                "entries": service.settings.cache_max_entries,
                "charged_bytes": service.settings.cache_max_bytes,
            }
            for field, limit in limits.items():
                if type(snapshot[field]) is not int or not 0 <= snapshot[field] <= limit:
                    raise ValueError("Invalid cache gauge.")
            gauges.update({f"recsys_cache_{field}": snapshot[field] for field in limits})
            gauges["recsys_cache_sample_success"] = 1
        except Exception:
            gauges["recsys_cache_sample_success"] = 0
            with self._lock:
                self._errors += 1
        try:
            rss = self._rss()
            if type(rss) is not int or rss < 0:
                raise ValueError("Invalid process RSS sample.")
            gauges["recsys_process_resident_memory_bytes"] = rss
            gauges["recsys_memory_sample_success"] = 1
        except Exception:
            gauges["recsys_memory_sample_success"] = 0
            with self._lock:
                self._errors += 1
        with self._lock:
            counts = sorted(self._counts.items())
            histograms = [
                (key, (row[0], row[1], tuple(row[2])))
                for key, row in sorted(self._histograms.items())
            ]
            gauges["recsys_observer_errors_total"] = self._errors
            gauges["recsys_primary_in_flight"] = self._active
            startup, model = self._startup, self._model
        if startup is not None:
            gauges["recsys_startup_duration_seconds"] = startup
        lines = []
        declared = set()

        def sample(name, kind, dimensions, value, family=None):
            family = family or name
            if family not in declared:
                lines.extend(
                    (
                        f"# HELP {family} Local snapshot service {family.removeprefix('recsys_')}.",
                        f"# TYPE {family} {kind}",
                    )
                )
                declared.add(family)
            lines.append(f"{name}{labels(dimensions)} {value}")

        for (name, dimensions), value in counts:
            sample(name, "counter", dimensions, value)
        for (name, dimensions), (count, total, buckets) in histograms:
            for bound, value in zip((*BOUNDS, "+Inf"), (*buckets, count), strict=True):
                sample(
                    name + "_bucket", "histogram", (*dimensions, ("le", str(bound))), value, name
                )
            sample(name + "_sum", "histogram", dimensions, total, name)
            sample(name + "_count", "histogram", dimensions, count, name)
        for name, value in sorted(gauges.items()):
            sample(name, "counter" if name.endswith("_total") else "gauge", (), value)
        for value in ("starting", "ready", "failed", "stopped"):
            sample("recsys_state", "gauge", (("state", value),), int(state.value == value))
        if model:
            sample(
                "recsys_model_info",
                "gauge",
                (("version", model[0]), ("manifest_sha256", model[1])),
                1,
            )
        return "\n".join(lines) + "\n"
