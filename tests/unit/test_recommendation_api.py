"""HTTP contract, lifecycle and cancellation checks without training data."""

# Optional service dependencies must be checked before imports that require them.
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
import httpx2 as httpx
from fastapi.testclient import TestClient

from ecommerce_recsys.artifacts import Recommendation
from ecommerce_recsys.serving.app import create_app
from ecommerce_recsys.serving.boundary import BODY_LIMIT, RequestBoundary
from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.service import (
    InferenceFailed,
    RecommendationService,
    StartupFailed,
    State,
)

ASYNC_TIMEOUT = 15
WORKER_TIMEOUT = 60


class SnapshotFixture:
    def __init__(self):
        self.manifest = {"bundle_version": "fixture-v1", "snapshot": {"cutoff": 99}}
        self.items = ("a", "b", "seen")
        self.user_index = {"known": 0}
        self.blocking = False
        self.fail = False
        self.transform = lambda result: result
        self.release = Event()
        self.release.set()
        self.entered = Event()
        self.guard = Lock()
        self.active = self.max_active = 0

    def context(self, user_id):
        return SimpleNamespace(history=("seen",) if user_id in self.user_index else ())

    def recommend(self, user_id=None, *, k=20):
        with self.guard:
            self.active += 1
            self.max_active = max(self.active, self.max_active)
        try:
            if self.blocking:
                self.entered.set()
                if not self.release.wait(WORKER_TIMEOUT):
                    raise TimeoutError("Fixture was not released.")
            if self.fail:
                raise ValueError("private user input and model path must not reach HTTP")
            return self.transform(
                Recommendation(
                    ("a", "b")[:k],
                    "hybrid_learned" if user_id in self.user_index else "recent_popularity",
                    "fixture-v1",
                    99,
                )
            )
        finally:
            with self.guard:
                self.active -= 1


@pytest.fixture
def api(tmp_path):
    snapshot, loads = SnapshotFixture(), []
    settings = ServiceSettings(tmp_path / "bundle", "a" * 64)

    def loader(path, *, expected_manifest_sha256):
        loads.append((path, expected_manifest_sha256))
        return snapshot

    return create_app(settings, loader=loader), snapshot, loads


def check_request_id(response):
    request_id = response.json()["request_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert response.headers["x-request-id"] == request_id


def test_no_eager_load_lifecycle_and_single_snapshot(api):
    app, _, loads = api
    assert not loads
    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.post("/v1/recommendations", json={}).json()["error"]["code"] == "not_ready"
    with client:
        assert len(loads) == 1 and loads[0][1] == "a" * 64
        ready = client.get("/health/ready")
        assert ready.status_code == 200 and ready.json()["bundle_version"] == "fixture-v1"
        for _ in range(5):
            warm = client.post("/v1/recommendations", json={"user_id": "known", "k": 2})
            check_request_id(warm)
            assert warm.json()["route"] == "hybrid_learned"
            assert warm.json()["items"] == ["a", "b"]
        assert len(loads) == 1
    assert app.state.service.state == State.STOPPED
    assert app.state.service.bundle is None
    assert client.get("/health/ready").status_code == 503


def test_unknown_null_and_opaque_ids_short_output_and_prefix(api):
    app, snapshot, _ = api
    with TestClient(app) as client:
        full = client.post("/v1/recommendations", json={"user_id": "known"}).json()
        assert full["items"] == ["a", "b"]  # A short result is not filled artificially.
        prefix = client.post("/v1/recommendations", json={"user_id": "known", "k": 1}).json()
        assert prefix["items"] == full["items"][:1]
        for data in ({}, {"user_id": None}, {"user_id": "new"}, {"user_id": " known "}):
            response = client.post("/v1/recommendations", json=data)
            assert response.status_code == 200 and response.json()["route"] == "recent_popularity"
        snapshot.transform = lambda result: replace(result, items=())
        empty = client.post("/v1/recommendations", json={"user_id": "known"})
        assert empty.status_code == 200 and empty.json()["items"] == []


@pytest.mark.parametrize("value", [0, -1, 21, True, False, 1.0, 2.5, "2", None, [], {}])
def test_strict_output_limit(api, value):
    with TestClient(api[0]) as client:
        response = client.post("/v1/recommendations", json={"k": value})
        assert response.status_code == 422
        assert response.json()["error"]["fields"] == ["k"]
        check_request_id(response)


@pytest.mark.parametrize(
    "value", ["", " ", "\x00", "a\nb", "\x7f", "x" * 129, True, 1, 1.5, [], {}]
)
def test_strict_user_id(api, value):
    with TestClient(api[0]) as client:
        response = client.post("/v1/recommendations", json={"user_id": value})
        assert response.status_code == 422
        assert response.json()["error"]["fields"] == ["user_id"]


@pytest.mark.parametrize(
    "value",
    [
        {"history": ["private-id"]},
        {"bundle_version": "other"},
        {"private-extra-key": "private-value"},
        [1],
        None,
    ],
)
def test_schema_errors_do_not_echo_input(api, value):
    with TestClient(api[0]) as client:
        response = client.post(
            "/v1/recommendations",
            content=json.dumps(value),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "private" not in response.text and "input" not in response.json()["error"]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b'{"k":1,"k":2}',
        b'{"k":NaN}',
        b'{"k":1e400}',
        b'{"k":Infinity}',
        b'{"k":-Infinity}',
        b'"\xff"',
        b"[" * 1200,
    ],
)
def test_invalid_json_rejected_before_inference(api, body):
    with TestClient(api[0]) as client:
        response = client.post(
            "/v1/recommendations", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_json"
        check_request_id(response)


def test_content_type_limits_and_http_errors(api):
    with TestClient(api[0]) as client:
        assert client.post("/v1/recommendations", content="{}").status_code == 415
        assert (
            client.post(
                "/v1/recommendations", content="{}", headers={"Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        oversized = client.post(
            "/v1/recommendations",
            content=b" " * (BODY_LIMIT + 1),
            headers={"Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        query = client.post("/v1/recommendations?k=1", json={})
        assert query.status_code == 422
        for response in (client.get("/not-found"), client.get("/v1/recommendations")):
            assert response.status_code in {404, 405}
            check_request_id(response)
        schema = client.get("/openapi.json").json()
        request = schema["components"]["schemas"]["RecommendationRequest"]
        assert request["additionalProperties"] is False
        assert request["properties"]["k"]["minimum"] == 1
        assert request["properties"]["k"]["maximum"] == 20
        assert "503" in schema["paths"]["/v1/recommendations"]["post"]["responses"]
        assert {"404", "405"}.issubset(schema["paths"]["/v1/recommendations"]["post"]["responses"])


@pytest.mark.parametrize(
    "headers,chunks,expected",
    [
        ([], [b" " * 4096, b" " * 4096, b"x"], 413),
        ([], [b"x" * (BODY_LIMIT + 1)], 413),
        ([(b"content-length", b"9000")], [b"{}"], 413),
        ([(b"content-length", b"3")], [b"{}"], 400),
        ([(b"content-length", b"-1")], [b"{}"], 400),
        ([(b"content-length", b"2"), (b"content-length", b"2")], [b"{}"], 400),
        ([(b"content-length", b"9" * 5000)], [b"{}"], 400),
    ],
)
def test_asgi_chunked_body_and_malformed_length(headers, chunks, expected, monkeypatch):
    class BoundedBuffer(bytearray):
        def extend(self, chunk):
            assert len(self) + len(chunk) <= BODY_LIMIT, "Oversized chunk copied before rejection"
            super().extend(chunk)

    monkeypatch.setattr("ecommerce_recsys.serving.boundary.bytearray", BoundedBuffer, raising=False)

    async def scenario():
        messages = [
            {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
            for i, chunk in enumerate(chunks)
        ]
        sent = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        async def forbidden(*args):
            raise AssertionError("Rejected body reached the endpoint")

        await RequestBoundary(forbidden)(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/recommendations",
                "headers": [(b"content-type", b"application/json"), *headers],
            },
            receive,
            send,
        )
        assert sent[0]["status"] == expected

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    ["duplicate", "seen", "catalog", "route", "version", "cutoff", "type", "limit", "exception"],
)
def test_model_failure_marks_unready_without_hidden_fallback(api, change):
    app, snapshot, _ = api
    with TestClient(app) as client:
        snapshot.transform = {
            "duplicate": lambda r: replace(r, items=("a", "a")),
            "seen": lambda r: replace(r, items=("seen",)),
            "catalog": lambda r: replace(r, items=("outside",)),
            "route": lambda r: replace(r, route="recent_popularity"),
            "version": lambda r: replace(r, bundle_version="wrong-v1"),
            "cutoff": lambda r: replace(r, cutoff=1),
            "type": lambda r: SimpleNamespace(items="ab"),
            "limit": lambda r: replace(r, items=("a", "b")),
            "exception": lambda r: r,
        }[change]
        snapshot.fail = change == "exception"
        response = client.post("/v1/recommendations", json={"user_id": "known", "k": 1})
        assert (
            response.status_code == 500 and response.json()["error"]["code"] == "inference_failed"
        )
        assert "private" not in response.text and "Traceback" not in response.text
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.post("/v1/recommendations", json={}).status_code == 503


def test_failed_startup_releases_resources_and_requires_pin(tmp_path):
    settings = ServiceSettings(tmp_path, "a" * 64)

    def fail(*args, **kwargs):
        raise ValueError("private missing path or wrong checksum")

    app = create_app(settings, loader=fail)
    with pytest.raises(StartupFailed, match="startup failed"):
        with TestClient(app):
            pass
    assert app.state.service.state == State.FAILED and app.state.service.bundle is None
    assert app.state.service.executor is None
    snapshot = SnapshotFixture()
    with TestClient(create_app(settings, loader=lambda *a, **k: snapshot)) as client:
        assert client.get("/health/ready").status_code == 200
    for invalid in (None, "", "x" * 64, "A" * 64, "0" * 63):
        with pytest.raises(ValueError):
            ServiceSettings(tmp_path, invalid)


def test_model_output_cannot_exceed_twenty_even_if_catalog_contains_it(api):
    app, snapshot, _ = api
    snapshot.items = (*snapshot.items, *(f"item-{index}" for index in range(21)))
    with TestClient(app) as client:
        snapshot.transform = lambda r: replace(
            r, items=tuple(f"item-{index}" for index in range(21))
        )
        result = client.post("/v1/recommendations", json={"user_id": "known", "k": 20})
        assert result.status_code == 500
        assert result.json()["error"]["code"] == "inference_failed"
        assert client.get("/health/ready").status_code == 503


@pytest.mark.parametrize(
    "user_id,k", [(None, 1000), (None, True), (None, 1.0), (None, 0), (1, 20), ("", 20)]
)
def test_direct_service_rejects_invalid_input_before_model_execution(api, user_id, k):
    async def scenario():
        service = api[0].state.service
        await service.start()
        try:
            with pytest.raises(ValueError):
                await service.recommend(user_id, k, "direct")
            assert service.state == State.READY
            assert (await service.recommend(None, 1, "valid")).items == ["a"]
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_environment_config_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("RECSYS_BUNDLE_PATH", raising=False)
    monkeypatch.delenv("RECSYS_MANIFEST_SHA256", raising=False)
    with pytest.raises(ValueError, match="required"):
        create_app()
    monkeypatch.setenv("RECSYS_BUNDLE_PATH", str(tmp_path))
    monkeypatch.setenv("RECSYS_MANIFEST_SHA256", "a" * 64)
    assert ServiceSettings.from_environment() == ServiceSettings(tmp_path, "a" * 64)


def test_busy_health_cancellation_and_shutdown_preserve_single_worker(api):
    async def scenario():
        app, snapshot, _ = api
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                snapshot.blocking = True
                snapshot.release.clear()
                pending = asyncio.create_task(
                    client.post("/v1/recommendations", json={"user_id": "known"})
                )
                assert await asyncio.to_thread(snapshot.entered.wait, ASYNC_TIMEOUT)
                try:
                    busy = await asyncio.wait_for(
                        client.post("/v1/recommendations", json={}), ASYNC_TIMEOUT
                    )
                    assert busy.status_code == 503 and busy.json()["error"]["code"] == "busy"
                    assert busy.headers["retry-after"] == "1"
                    assert (
                        await asyncio.wait_for(client.get("/health/live"), ASYNC_TIMEOUT)
                    ).status_code == 200
                    assert (await client.get("/health/ready")).status_code == 200
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    assert (await client.post("/v1/recommendations", json={})).status_code == 503
                    stopped = asyncio.create_task(app.state.service.stop())
                    stopped_again = asyncio.create_task(app.state.service.stop())
                    await asyncio.sleep(0.02)
                    assert not stopped.done()
                    assert not stopped_again.done()
                    assert app.state.service.bundle is snapshot
                    assert (await client.get("/health/ready")).status_code == 503
                finally:
                    snapshot.release.set()
                await asyncio.wait_for(stopped, ASYNC_TIMEOUT)
                await asyncio.wait_for(stopped_again, ASYNC_TIMEOUT)
                assert snapshot.max_active == 1
                assert app.state.service.bundle is None
        # The cancelled request must not strand global admission for a new service.
        new = RecommendationService(
            ServiceSettings(Path("unused"), "a" * 64), loader=lambda *a, **k: SnapshotFixture()
        )
        await new.start()
        await new.stop()

    asyncio.run(scenario())


def test_inference_is_serialized_across_app_instances(api, tmp_path):
    async def scenario():
        first, snapshot, _ = api
        second = create_app(
            ServiceSettings(tmp_path, "a" * 64), loader=lambda *a, **k: SnapshotFixture()
        )
        async with first.router.lifespan_context(first), second.router.lifespan_context(second):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=first), base_url="http://first"
            ) as a:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=second), base_url="http://second"
                ) as b:
                    snapshot.blocking = True
                    snapshot.release.clear()
                    pending = asyncio.create_task(a.post("/v1/recommendations", json={}))
                    assert await asyncio.to_thread(snapshot.entered.wait, ASYNC_TIMEOUT)
                    try:
                        assert (await b.post("/v1/recommendations", json={})).status_code == 503
                    finally:
                        snapshot.release.set()
                    assert (await pending).status_code == 200
                    assert (await b.post("/v1/recommendations", json={})).status_code == 200

    asyncio.run(scenario())


def test_submission_failure_releases_admission(api, monkeypatch):
    async def scenario():
        service = api[0].state.service
        await service.start()

        def fail(*args, **kwargs):
            raise RuntimeError("executor unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(service.executor, "submit", fail)
            with pytest.raises(InferenceFailed):
                await service.recommend(None, 20, "test")
        assert service.state == State.FAILED
        await service.stop()
        next_service = api[0].state.service.__class__(service.settings, loader=service.loader)
        await next_service.start()
        await next_service.stop()

    asyncio.run(scenario())
