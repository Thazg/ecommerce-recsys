"""Telemetry accounting, bounded dimensions, redaction and failure isolation."""

# ruff: noqa: E402

import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
import httpx2 as httpx
from serving_test_support import TestClient
from test_service_cache import application

from ecommerce_recsys.serving.observability import BOUNDS, EVENT_LOGGER, Telemetry
from ecommerce_recsys.serving.service import _PROCESS_PERMIT


@pytest.fixture(autouse=True)
def capture_owned_events(monkeypatch):
    monkeypatch.setattr(EVENT_LOGGER, "propagate", True)


def samples(text):
    result = {}
    assert text.endswith("\n")
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? ([0-9.eE+\-]+)", line)
        assert match, line
        name, raw, value = match.groups()
        dimensions = tuple(
            (key, json.loads(value))
            for key, value in re.findall(r'(\w+)=("(?:\\.|[^"\\])*")', raw or "")
        )
        key = (name, dimensions)
        assert key not in result
        result[key] = float(value)
    return result


def total(data, name, **dimensions):
    return sum(
        value
        for (metric, labels), value in data.items()
        if metric == name and all(dict(labels).get(k) == v for k, v in dimensions.items())
    )


def test_real_http_accounting_and_separate_registries(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER.name)
    app, _ = application(tmp_path, cache_max_entries=8)
    app.state.service.telemetry._rss = lambda: 1024
    with TestClient(app) as client:
        for k in (5, 20):
            assert (
                client.post("/v1/recommendations", json={"user_id": "known", "k": k}).status_code
                == 200
            )
        assert (
            client.post(
                "/v1/recommendations", json={"user_id": "secret-user", "k": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/recommendations",
                content=b'{"k":NaN}',
                headers={"Content-Type": "application/json"},
            ).status_code
            == 400
        )
        assert client.get("/secret-path?secret-query").status_code == 404
        response = client.get("/metrics")
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
        data = samples(response.text)
        assert total(data, "recsys_http_requests_total") == 5
        assert total(data, "recsys_deliveries_total", cache="miss") == 1
        assert total(data, "recsys_deliveries_total", cache="hit") == 1
        assert total(data, "recsys_primary_calls_total") == 1
        assert total(data, "recsys_cache_events_total", event="hits") == 1
        assert total(data, "recsys_http_errors_total", code="validation_error") == 1
        assert total(data, "recsys_http_errors_total", code="invalid_json") == 1
        assert samples(client.get("/metrics").text) == data
        owned = [
            record.getMessage() for record in caplog.records if record.name == EVENT_LOGGER.name
        ]
        for text in [response.text, *owned]:
            assert not any(
                secret in text for secret in ("secret-user", "secret-path", "secret-query")
            )
        for value in owned:
            record = json.loads(value)
            assert "event" in record and "timestamp_unix_seconds" in record
            assert "user_id" not in record and "items" not in record
            if "degraded" in record:
                assert type(record["degraded"]) is bool
        for (name, dimensions), count in data.items():
            if name.endswith("_count"):
                assert (
                    data[name.removesuffix("_count") + "_bucket", (*dimensions, ("le", "+Inf"))]
                    == count
                )
    other, _ = application(tmp_path)
    with TestClient(other) as client:
        assert total(samples(client.get("/metrics").text), "recsys_http_requests_total") == 0


def test_histogram_boundaries_thread_safety_and_dimension_rejection():
    telemetry = Telemetry()
    scope = {"path": "/v1/recommendations", "method": "POST", "state": {}}

    def observe(_):
        telemetry.http(scope, 200, "completed", 0.005)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(observe, range(100)))
    row = telemetry._histograms[
        "recsys_http_duration_seconds", (("endpoint", "recommendations"), ("outcome", "completed"))
    ]
    assert row[0] == 100 and row[2][0] == 0 and all(value == 100 for value in row[2][1:])
    for i in range(100):
        telemetry.http({"path": f"/unknown-{i}", "method": f"METHOD{i}"}, 499, "completed", 0.1)
    assert len(telemetry._counts) == 2
    telemetry.admission("user-controlled-label")
    telemetry.cache_event("user-controlled-label")
    assert telemetry._errors == 2
    assert len(BOUNDS) == 10


def test_cache_events_survive_disable_and_sampling_fault_isolated(tmp_path, monkeypatch):
    app, _ = application(tmp_path, cache_max_entries=1, cache_ttl_seconds=5)
    service = app.state.service
    with TestClient(app) as client:
        now = [0.0]
        service.cache._clock = lambda: now[0]
        client.post("/v1/recommendations", json={"user_id": "known"})
        client.post("/v1/recommendations", json={"user_id": "other"})
        now[0] = 5.0
        client.post("/v1/recommendations", json={"user_id": "other"})
        service._disable_cache()
        monkeypatch.setattr(
            service.telemetry,
            "_rss",
            lambda: (_ for _ in ()).throw(OSError("private-memory-error")),
        )
        data = samples(client.get("/metrics").text)
        assert total(data, "recsys_cache_events_total", event="evictions") == 1
        assert total(data, "recsys_cache_events_total", event="expirations") == 1
        assert total(data, "recsys_cache_events_total", event="misses") == 3
        assert total(data, "recsys_cache_entries") == 0
        assert total(data, "recsys_memory_sample_success") == 0
        assert total(data, "recsys_observer_errors_total") >= 1
        assert client.post("/v1/recommendations", json={}).status_code == 200


def test_sink_failure_and_backend_exception_never_export_private_text(
    tmp_path, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER.name)
    app, model = application(tmp_path, cache_max_entries=8)
    with TestClient(app) as client:

        def bad_log(*args, **kwargs):
            raise OSError("sink-private-path")

        with monkeypatch.context() as patch:
            patch.setattr(EVENT_LOGGER, "info", bad_log)
            assert client.post("/v1/recommendations", json={"user_id": "known"}).status_code == 200
        assert total(samples(client.get("/metrics").text), "recsys_observer_errors_total") >= 1

        def fail(*args, **kwargs):
            raise ValueError("secret-user secret-item C:/secret/path")

        monkeypatch.setattr(model, "recommend", fail)
        assert client.post("/v1/recommendations", json={"user_id": "other"}).status_code == 500
        text = client.get("/metrics").text
        assert total(samples(text), "recsys_ready") == 0
        assert total(samples(text), "recsys_primary_duration_seconds_count", outcome="failed") == 1
        owned = [r.getMessage() for r in caplog.records if r.name == EVENT_LOGGER.name]
        assert not any(
            "secret" in value or "sink-private-path" in value for value in [text, *owned]
        )
        assert all(not r.exc_info for r in caplog.records if r.name == EVENT_LOGGER.name)


@pytest.mark.parametrize("busy_policy", ["reject", "recent_popularity"])
def test_cancelled_http_and_running_worker_are_distinct_observations(tmp_path, busy_policy):
    async def scenario():
        app, model = application(tmp_path, cache_max_entries=8, busy_policy=busy_policy)
        service = app.state.service
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                model.blocking = True
                model.release.clear()
                pending = asyncio.create_task(
                    client.post("/v1/recommendations", json={"user_id": "known"})
                )
                try:
                    assert await asyncio.to_thread(model.entered.wait, 15)
                    text = (await client.get("/metrics")).text
                    assert total(samples(text), "recsys_primary_in_flight") == 1
                    busy = await client.post("/v1/recommendations", json={"user_id": "other"})
                    assert busy.status_code == (503 if busy_policy == "reject" else 200)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    data = samples((await client.get("/metrics")).text)
                    assert total(data, "recsys_http_requests_total", outcome="cancelled") == 1
                    assert total(data, "recsys_primary_in_flight") == 1
                    assert not _PROCESS_PERMIT.acquire(blocking=False)
                    assert (
                        total(
                            data,
                            "recsys_admission_total",
                            decision="busy_rejected"
                            if busy_policy == "reject"
                            else "busy_fallback",
                        )
                        == 1
                    )
                    assert total(data, "recsys_deliveries_total", degraded="true") == (
                        busy_policy == "recent_popularity"
                    )
                finally:
                    model.release.set()
                await asyncio.get_running_loop().run_in_executor(service.executor, lambda: None)
                data = samples((await client.get("/metrics")).text)
                assert total(data, "recsys_primary_in_flight") == 0
                assert total(data, "recsys_primary_duration_seconds_count", outcome="success") == 1

    asyncio.run(scenario())
