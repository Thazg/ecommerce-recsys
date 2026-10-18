"""Prospective local security policy, input budgets and owned-resource edges."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import http.client
import json
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
from serving_test_support import TestClient
from test_service_cache import Snapshot

from ecommerce_recsys.serving.app import create_app
from ecommerce_recsys.serving.boundary import RequestBoundary
from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.observability import EVENT_LOGGER
from ecommerce_recsys.serving.rate_limit import RequestAdmission
from ecommerce_recsys.serving.security import SecuritySettings, authority


def application(tmp_path, **policy):
    snapshot = Snapshot()
    security = SecuritySettings(**policy)
    return create_app(
        ServiceSettings(tmp_path, "a" * 64), loader=lambda *a, **k: snapshot, security=security
    ), snapshot


@pytest.mark.parametrize(
    "field",
    [
        "body_readers",
        "global_burst",
        "peer_burst",
        "peer_entries",
        "max_connections",
        "header_limit",
        "target_limit",
    ],
)
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, float("nan"), 1000000])
def test_plain_integer_limits_fail_closed(field, value):
    with pytest.raises(ValueError, match="setting"):
        SecuritySettings(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "body_timeout_seconds",
        "header_timeout_seconds",
        "global_rate",
        "peer_rate",
        "peer_ttl_seconds",
    ],
)
@pytest.mark.parametrize(
    "value", [True, 0, -1, 5e-324, float("nan"), float("inf"), 1000000, 10**400, -(10**400)]
)
def test_finite_positive_limits_fail_closed(field, value):
    with pytest.raises(ValueError, match="setting"):
        SecuritySettings(**{field: value})


@pytest.mark.parametrize(
    "value",
    [
        "localhost.",
        "evil.example",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:",
        "localhost:80/path",
        "localhost?x",
        "localhost#x",
        "user@localhost",
        " localhost",
        "localhost\t",
        "127.1",
        "[::1%scope]:8000",
        "::1",
        "localhost\\evil",
        "localhost#",
        "localhost?",
        "[::1]garbage",
        "[::1]:80#",
        "localhost\x00",
    ],
)
def test_authority_rejects_normalization_and_rebinding_gaps(value):
    with pytest.raises(ValueError):
        authority(value)


def test_ipv6_matching_ports_and_same_origin_are_explicit():
    policy = SecuritySettings()
    assert policy.valid_host(b"[::1]:8000")
    assert policy.valid_host(b"LOCALHOST:8000")
    assert not policy.valid_host(b"127.0.0.1:8001")
    assert not policy.valid_host(b"127.0.0.2:8000")
    assert policy.valid_origin(b"http://[::1]:8000", b"[::1]:8000")
    assert not policy.valid_origin(b"http://localhost:8000", b"127.0.0.1:8000")


def test_secret_sources_are_exclusive_bounded_and_never_in_repr(tmp_path, monkeypatch):
    token = "secret-sentinel-" + "x" * 32
    monkeypatch.delenv("RECSYS_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("RECSYS_API_TOKEN", token)
    policy = SecuritySettings.from_environment(authorities=("localhost:8000",))
    assert token not in repr(policy) + json.dumps(policy.public_policy())
    assert policy.authenticated([b"Bearer " + token.encode()])
    file = tmp_path / "private-token-path"
    file.write_bytes(token.encode() + b"\r\n")
    monkeypatch.setenv("RECSYS_API_TOKEN_FILE", str(file))
    with pytest.raises(ValueError, match="only one"):
        SecuritySettings.from_environment(authorities=("localhost:8000",))
    monkeypatch.delenv("RECSYS_API_TOKEN")
    assert (
        SecuritySettings.from_environment(authorities=("localhost:8000",)).token == token.encode()
    )
    file.write_bytes(b"x" * 100000)
    with pytest.raises(ValueError, match="API token"):
        SecuritySettings.from_environment(authorities=("localhost:8000",))
    file.unlink()
    with pytest.raises(ValueError) as caught:
        SecuritySettings.from_environment(authorities=("localhost:8000",))
    assert str(file) not in str(caught.value)


@pytest.mark.parametrize(
    "token", [b"", b"x" * 31, b"x" * 257, b"x" * 31 + b" ", b"x" * 32 + b"\n", b"\xff" * 32]
)
def test_invalid_secret_is_rejected_without_echo(token):
    with pytest.raises(ValueError, match="API token"):
        SecuritySettings(token=token)


def test_token_buckets_are_atomic_bounded_and_deterministic():
    now = [0.0]
    policy = SecuritySettings(
        global_rate=1, global_burst=2, peer_rate=1, peer_burst=1, peer_entries=2, peer_ttl_seconds=2
    )
    admission = RequestAdmission(policy, clock=lambda: now[0])
    assert admission.attempt("a") == 0
    assert admission.attempt("a") == 1
    assert admission.global_bucket.tokens == 1  # A denial did not partially charge global.
    assert admission.attempt("b") == 0
    assert admission.attempt("c") == 2
    assert set(admission.peers) == {"a", "b"}
    now[0] = 0.5
    assert admission.attempt("a") == 1
    now[0] = 1.0
    assert admission.attempt("a") == 0
    now[0] = 3.0
    assert admission.attempt("c") == 0
    assert set(admission.peers) == {"c"}
    with ThreadPoolExecutor(max_workers=10) as pool:
        attempts = list(pool.map(admission.attempt, ["d"] * 20))
    assert attempts.count(0) == 1


@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({"Host": "evil.example"}, 400, "invalid_host"),
        ({"Host": "127.0.0.1:9999"}, 400, "invalid_host"),
        ({"Origin": "null"}, 403, "forbidden_origin"),
        ({"Origin": "http://evil.example"}, 403, "forbidden_origin"),
        ({"Origin": "http://user@127.0.0.1:8000"}, 403, "forbidden_origin"),
        ({"Origin": "http://127.0.0.1:8000/"}, 403, "forbidden_origin"),
        ({"Content-Encoding": "gzip"}, 415, "unsupported_media_type"),
        ({"X-Bloat": "x" * 17000}, 431, "headers_too_large"),
    ],
)
def test_early_guards_never_execute_models_or_degrade_readiness(tmp_path, headers, status, code):
    app, model = application(tmp_path)
    with TestClient(app) as client:
        before = len(model.calls)
        response = client.post("/v1/recommendations", json={}, headers=headers)
        assert response.status_code == status and response.json()["error"]["code"] == code
        assert response.headers["connection"] == "close"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-request-id"] == response.json()["request_id"]
        assert len(model.calls) == before
        assert client.get("/health/ready").status_code == 200
        counts = app.state.service.telemetry._counts
        assert counts["recsys_http_errors_total", (("code", code),)] == 1
        assert not any(name == "recsys_deliveries_total" for name, _ in counts)


def test_rate_limits_cover_cache_aliases_unknown_users_and_forwarded_spoofing(tmp_path):
    app, model = application(tmp_path, peer_rate=0.01, peer_burst=2)
    with TestClient(app) as client:
        for user in ("new-a", "new-b"):
            assert client.post("/v1/recommendations", json={"user_id": user}).status_code == 200
        calls = len(model.calls)
        response = client.post(
            "/v1/recommendations/",
            json={"user_id": "new-c"},
            headers={"X-Forwarded-For": "127.0.0.99", "Forwarded": "for=127.0.0.98"},
        )
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0
        assert len(model.calls) == calls
        assert client.get("/health/ready").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_bearer_protects_operational_endpoints_and_never_logs_secret(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(EVENT_LOGGER, "propagate", True)
    caplog.set_level(logging.INFO, logger=EVENT_LOGGER.name)
    token = b"sentinel-secret-" + b"x" * 32
    app, _ = application(tmp_path, token=token)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        for path in ("/health/ready", "/metrics", "/openapi.json", "/docs", "/redoc"):
            response = client.get(path)
            assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
        for value in ("wrong", "Basic " + token.decode(), "Bearer  " + token.decode()):
            assert (
                client.post(
                    "/v1/recommendations", json={}, headers={"Authorization": value}
                ).status_code
                == 401
            )
        client.headers["Authorization"] = "Bearer " + token.decode()
        assert client.get("/health/ready").status_code == 200
        assert client.post("/v1/recommendations", json={}).status_code == 200
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == "1.2.0"
        assert schema["paths"]["/v1/recommendations"]["post"]["security"] == [{"BearerAuth": []}]
        assert client.get("/docs").status_code == 404
        assert client.get("/metrics").status_code == 200
        assert token.decode() not in caplog.text + json.dumps(schema) + repr(app.state.security)
        assert "http_request" in caplog.text


def scope(headers=()):
    return {
        "type": "http",
        "method": "POST",
        "path": "/v1/recommendations",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"content-type", b"application/json"),
            *headers,
        ],
    }


def test_absolute_body_deadline_and_reader_ownership_across_cancellation():
    async def scenario():
        policy = SecuritySettings(body_timeout_seconds=0.08, body_readers=1)
        admission = RequestAdmission(policy)
        sent = []
        entered = asyncio.Event()

        async def endpoint(*args):
            raise AssertionError("Incomplete body reached the model endpoint")

        async def dribble():
            entered.set()
            await asyncio.sleep(0.03)
            return {"type": "http.request", "body": b" ", "more_body": True}

        async def send(message):
            sent.append(message)

        boundary = RequestBoundary(endpoint, security=policy, admission=admission)
        first = asyncio.create_task(boundary(scope(), dribble, send))
        await entered.wait()
        overflow = []

        async def collect(message):
            overflow.append(message)

        await boundary(scope(), dribble, collect)
        assert overflow[0]["status"] == 503
        await first
        assert sent[0]["status"] == 408 and admission.readers == 0
        entered.clear()
        second = asyncio.create_task(boundary(scope(), dribble, send))
        await entered.wait()
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert admission.readers == 0

        async def disconnected():
            return {"type": "http.disconnect"}

        await boundary(scope(), disconnected, send)
        assert admission.readers == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "headers,code",
    [
        ([(b"host", b"127.0.0.1:8000")], "invalid_host"),
        ([(b"origin", b"http://127.0.0.1:8000")] * 2, "forbidden_origin"),
        ([(b"content-length", b"2"), (b"transfer-encoding", b"chunked")], "invalid_request"),
        ([(b"authorization", b"Bearer " + b"x" * 32)] * 2, "unauthorized"),
        ([(b"trailer", b"X-Extra")], "invalid_request"),
    ],
)
def test_duplicate_and_ambiguous_headers_do_not_read_body(headers, code):
    async def scenario():
        policy = SecuritySettings(token=b"x" * 32) if code == "unauthorized" else SecuritySettings()

        async def forbidden(*args):
            raise AssertionError("Early rejection read or executed request")

        sent = []

        async def send(message):
            sent.append(message)

        await RequestBoundary(forbidden, security=policy)(scope(headers), forbidden, send)
        assert json.loads(sent[-1]["body"])["error"]["code"] == code

    asyncio.run(scenario())


def test_idle_state_cannot_refresh_bursts_before_refill():
    with pytest.raises(ValueError, match="full refill"):
        replace(SecuritySettings(), peer_ttl_seconds=0.5)


@pytest.mark.parametrize("path", ["/v1/recommendations/", "/health/live", "/missing"])
def test_unsupported_body_paths_close_before_reading(tmp_path, path):
    app, _ = application(tmp_path)
    with TestClient(app) as client:
        response = client.request(
            "POST", path, content=b"{", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400 and response.headers["connection"] == "close"
        assert app.state.request_admission.readers == 0


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_shared_encoding_error_is_declared_in_openapi(tmp_path, path):
    app, _ = application(tmp_path)
    with TestClient(app) as client:
        response = client.get(path, headers={"Content-Encoding": "gzip"})
        assert response.status_code == 415
        schema = client.get("/openapi.json").json()
        error = schema["paths"][path]["get"]["responses"]["415"]
        assert error["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("size", [1, 17000])
def test_undeclared_chunked_trailers_never_reach_the_model(tmp_path, size, split):
    from test_http_protocol_guards import listener, read_response

    app, _ = application(tmp_path)
    with listener(app=app, lifespan="on", header_timeout_seconds=5) as server:
        with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
            prefix = (
                b"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
                b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n"
            )
            ending = b"0\r\nX-Extra: " + b"a" * size + b"\r\n\r\n"
            if split:
                sock.sendall(prefix)
                deadline = time.monotonic() + 10
                while app.state.request_admission.readers != 1:
                    assert time.monotonic() < deadline
                    time.sleep(0.005)
                sock.sendall(ending)
            else:
                sock.sendall(prefix + ending)
            assert b"400 Bad Request" in read_response(sock)
        deadline = time.monotonic() + 10
        while app.state.request_admission.readers:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert sum(server.counts.values()) == 1
        assert set(server.counts) <= {"trailers_rejected", "invalid_http"}
        if size == 1:
            assert server.counts == {"trailers_rejected": 1}
        assert app.state.service.primary_calls == 0
        assert app.state.service.readiness()[1]


def test_declared_trailers_are_rejected_before_asgi_and_body_reads(tmp_path):
    from test_http_protocol_guards import listener, read_response

    app, _ = application(tmp_path)
    with listener(app=app, lifespan="on", header_timeout_seconds=5) as server:
        with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
            sock.sendall(
                b"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
                b"Transfer-Encoding: chunked\r\nTrailer: X-Extra\r\n\r\n"
            )
            assert b"400 Bad Request" in read_response(sock)
        assert server.counts == {"trailers_rejected": 1}
        assert app.state.request_admission.readers == 0
        assert not app.state.request_admission.peers
        assert app.state.service.primary_calls == 0


def test_real_probe_trailer_handshake_and_transport_accounting(tmp_path):
    from test_http_protocol_guards import listener

    from scripts.verify_service_hardening import trailer_probes

    app, _ = application(tmp_path)
    with listener(app=app, lifespan="on", header_timeout_seconds=5) as server:
        trailer_probes(server.port, b"Host: 127.0.0.1:8000\r\n", b"")
        deadline = time.monotonic() + 10
        while app.state.request_admission.readers:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert sum(server.counts.values()) == 2
        assert server.counts["trailers_rejected"] >= 1
        assert set(server.counts) <= {"trailers_rejected", "invalid_http"}
        assert app.state.service.primary_calls == 0
        assert app.state.service.readiness()[1]


def test_plain_chunked_json_remains_supported(tmp_path):
    from test_http_protocol_guards import listener

    app, _ = application(tmp_path)
    with listener(app=app, lifespan="on", header_timeout_seconds=5) as server:
        with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
            sock.sendall(
                b"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
                b"Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
            )
            response = http.client.HTTPResponse(sock)
            response.begin()
            assert response.status == 200
            assert json.loads(response.read())["route"] == "recent_popularity"
        assert not server.counts
        assert app.state.service.primary_calls == 1
        assert app.state.request_admission.readers == 0
