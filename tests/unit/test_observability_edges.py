"""Early HTTP exits, scraper failures and exporter invariants."""

# ruff: noqa: E402

import asyncio
import json

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
from fastapi.testclient import TestClient
from test_observability import samples, total
from test_service_cache import application

from ecommerce_recsys.serving.cache import ResultCache
from ecommerce_recsys.serving.observability import Telemetry
from ecommerce_recsys.serving.observation_boundary import ObservationBoundary
from scripts.verify_service_observability import parse_metrics


@pytest.mark.parametrize(
    "body,media,expected,code",
    [
        (b"x" * 8193, "application/json", 413, "body_too_large"),
        (b"{}", "text/plain", 415, "unsupported_media_type"),
        (b'{"k":1,"k":2}', "application/json", 400, "invalid_json"),
    ],
)
def test_early_rejects_count_once(tmp_path, body, media, expected, code):
    app, _ = application(tmp_path)
    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/recommendations", content=body, headers={"Content-Type": media}
            ).status_code
            == expected
        )
        data = samples(client.get("/metrics").text)
        assert total(data, "recsys_http_requests_total") == 1
        assert total(data, "recsys_http_errors_total", code=code) == 1
        assert total(data, "recsys_primary_calls_total") == 0


def test_disconnect_and_unexpected_exception_are_safe_and_observed():
    async def scenario():
        observer = Telemetry()

        async def disconnected(scope, receive, send):
            await receive()

        async def receive():
            return {"type": "http.disconnect"}

        sent = []

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "path": "/private-path",
            "method": "POST",
            "state": {"request_id": "a" * 32},
        }
        await ObservationBoundary(disconnected, telemetry=observer)(scope, receive, send)
        assert not sent

        async def failed(scope, receive, send):
            raise ValueError("private-exception")

        await ObservationBoundary(failed, telemetry=observer)(scope, receive, send)
        body = json.loads(sent[-1]["body"])
        assert body["error"]["code"] == "internal_error"
        assert "private" not in json.dumps(body)
        assert (
            sum(
                v
                for (name, dims), v in observer._counts.items()
                if name == "recsys_http_requests_total" and dict(dims)["outcome"] == "disconnected"
            )
            == 1
        )
        assert (
            sum(
                v
                for (name, dims), v in observer._counts.items()
                if name == "recsys_http_requests_total" and dict(dims)["status"] == "500"
            )
            == 1
        )

    asyncio.run(scenario())


def test_metric_read_does_not_expire_entries_or_mutate_bad_cache(tmp_path, monkeypatch):
    app, _ = application(tmp_path, cache_max_entries=8, cache_ttl_seconds=5)
    service = app.state.service
    with TestClient(app) as client:
        now = [0.0]
        service.cache._clock = lambda: now[0]
        client.post("/v1/recommendations", json={})
        now[0] = 5.0
        assert total(samples(client.get("/metrics").text), "recsys_cache_entries") == 1
        cache = service.cache
        monkeypatch.setattr(cache, "snapshot", lambda: {})
        assert total(samples(client.get("/metrics").text), "recsys_cache_sample_success") == 0
        assert service.cache is cache
        monkeypatch.setattr(service.telemetry, "render", lambda service: None)
        assert client.get("/metrics").status_code == 503
        assert client.post("/v1/recommendations", json={}).status_code == 200


def test_cache_event_sink_failure_does_not_break_storage():
    def fail(event):
        raise RuntimeError("private-observer")

    cache = ResultCache("n", max_entries=1, max_bytes=10000, ttl_seconds=10, on_event=fail)
    assert cache.get("u") is None
    from ecommerce_recsys.artifacts import Recommendation

    result = Recommendation(("i",), "recent_popularity", "v", 1)
    assert cache.put("u", result) and cache.get("u") == result


def test_actual_stream_handler_failure_is_counted_without_logging_recursion(monkeypatch):
    import logging

    from ecommerce_recsys.serving.observability import EVENT_LOGGER, EventStreamHandler

    class BrokenStream:
        def write(self, value):
            raise OSError("private-stream-path")

        def flush(self):
            pass

    monkeypatch.setattr(EVENT_LOGGER, "handlers", [EventStreamHandler(BrokenStream())])
    monkeypatch.setattr(EVENT_LOGGER, "propagate", False)
    previous = EVENT_LOGGER.level
    try:
        EVENT_LOGGER.setLevel(logging.INFO)
        telemetry = Telemetry()
        telemetry.event("cache_disabled")
        assert telemetry._errors == 1
    finally:
        EVENT_LOGGER.setLevel(previous)


@pytest.mark.parametrize(
    "text",
    [
        "metric 1\nmetric 2\n",
        "# TYPE metric gauge\nmetric{bad} 1\n",
        "# TYPE metric gauge\nmetric -1\n",
        "# TYPE metric gauge\nmetric 1e999\n",
        '# TYPE x histogram\nx_count 1\nx_bucket{le="+Inf"} 0\n',
    ],
)
def test_verifier_rejects_malformed_or_inconsistent_samples(text):
    with pytest.raises(ValueError):
        parse_metrics(text)


def test_actual_export_passes_independent_histogram_parser(tmp_path):
    app, _ = application(tmp_path, cache_max_entries=1)
    with TestClient(app) as client:
        client.post("/v1/recommendations", json={})
        parsed = parse_metrics(client.get("/metrics").text)
        assert any(name.endswith("_bucket") for name, labels in parsed)


def test_startup_failure_and_shutdown_identity_are_observable(tmp_path, monkeypatch):
    from ecommerce_recsys.serving.service import StartupFailed

    failed, model = application(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("private-startup-error")

    monkeypatch.setattr(model, "recommend", fail)
    with pytest.raises(StartupFailed):
        with TestClient(failed):
            pass
    service = failed.state.service
    data = samples(service.telemetry.render(service))
    assert total(data, "recsys_lifecycle_events_total", event="startup_failed") == 1
    assert total(data, "recsys_lifecycle_events_total", event="cleanup_complete") == 1
    assert total(data, "recsys_model_info") == total(data, "recsys_ready") == 0
    assert total(data, "recsys_primary_calls_total") == 0
    healthy, _ = application(tmp_path)
    with TestClient(healthy):
        pass
    data = samples(healthy.state.service.telemetry.render(healthy.state.service))
    assert total(data, "recsys_model_info") == 0
    assert total(data, "recsys_state", state="stopped") == 1
