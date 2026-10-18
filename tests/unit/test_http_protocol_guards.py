"""Exercise the pinned adapter with actual incomplete HTTP/1.1 sockets."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import socket
import time
from collections import Counter
from contextlib import contextmanager
from threading import Event, Thread
from types import SimpleNamespace

import pytest

pytest.importorskip("uvicorn", reason="Install requirements/serving-test.txt for protocol tests.")
import uvicorn

from ecommerce_recsys.serving.http_protocol import guarded_http_protocol
from ecommerce_recsys.serving.security import SecuritySettings


@contextmanager
def listener(*, app=None, lifespan="off", **limits):
    counts = Counter()
    entered, release = Event(), Event()
    release.set()

    async def simple(scope, receive, send):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    policy = SimpleNamespace(
        **{
            "max_connections": 4,
            "header_timeout_seconds": 0.4,
            "header_limit": 16384,
            "target_limit": 8192,
            **limits,
        }
    )
    telemetry = SimpleNamespace(transport=lambda event: counts.update([event]))
    protocol = guarded_http_protocol(policy, telemetry)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app or simple,
            http=protocol,
            loop="asyncio",
            lifespan=lifespan,
            ws="none",
            access_log=False,
            proxy_headers=False,
            timeout_keep_alive=5,
            log_level="critical",
        )
    )
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Fixture HTTP listener did not start.")
        time.sleep(0.01)
    try:
        yield SimpleNamespace(
            port=port, counts=counts, entered=entered, release=release, server=server
        )
    finally:
        release.set()
        server.should_exit = True
        thread.join(15)
        sock.close()
        assert not thread.is_alive()


def connect(server):
    return socket.create_connection(("127.0.0.1", server.port), timeout=10)


def read_until(sock, complete, *, initial=b""):
    result = initial
    while not complete(result):
        chunk = sock.recv(65536)
        if not chunk:
            raise EOFError("HTTP connection closed before the expected response completed.")
        result += chunk
    return result


def read_response(sock):
    result = read_until(sock, lambda data: b"\r\n\r\n" in data)
    if b"200 OK" in result:
        result = read_until(sock, lambda data: data.endswith(b"ok"), initial=result)
    return result


def test_absolute_header_timer_cannot_be_renewed_by_dribbling():
    with listener() as server, connect(server) as sock:
        sock.sendall(b"GET / HTTP/1.1\r\nHost:")
        time.sleep(0.22)
        try:
            sock.sendall(b" local")
        except (BrokenPipeError, ConnectionResetError):
            pass  # A delayed test thread may observe the already-enforced close.
        assert sock.recv(100) == b""
        assert server.counts["header_timeout"] == 1
        assert not server.entered.is_set()


def test_complete_request_disarms_timer_during_inference_and_rearms_keepalive():
    with listener() as server, connect(server) as sock:
        server.release.clear()
        sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert server.entered.wait(10)
        time.sleep(0.65)
        assert not server.counts
        server.release.set()
        assert b"200 OK" in read_response(sock)
        sock.sendall(b"GET / HTTP/1.1\r\nHost:")
        assert sock.recv(100) == b""
        assert server.counts["header_timeout"] == 1


def test_incomplete_connections_are_bounded_before_asgi():
    with listener(header_timeout_seconds=5, max_connections=2) as server:
        sockets = []
        try:
            for _ in range(3):
                sockets.append(connect(server))
            assert sockets[-1].recv(100) == b""
            assert server.counts["connection_limit"] == 1
            assert not server.entered.is_set()
        finally:
            for sock in sockets:
                sock.close()


@pytest.mark.parametrize(
    "data",
    [
        b"GET / HTTP/1.1\r\nHost: localhost\r\nX: " + b"a" * 17000 + b"\r\n\r\n",
        b"GET /" + b"a" * 8200 + b" HTTP/1.1\r\nHost: localhost\r\n\r\n",
    ],
)
def test_complete_input_limits_apply_before_asgi(data):
    with listener() as server, connect(server) as sock:
        sock.sendall(data)
        assert b"400 Bad Request" in read_response(sock)
        assert server.counts["input_limit"] == 1
        assert not server.entered.is_set()


def test_pipelined_request_keeps_new_cycle_free_of_old_timer():
    with listener() as server, connect(server) as sock:
        sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n" * 2)
        result = read_until(sock, lambda data: data.count(b"200 OK") >= 2 and data.endswith(b"ok"))
        assert result.count(b"200 OK") == 2
        assert not server.counts


def test_unaudited_protocol_upgrade_fails_closed(monkeypatch):
    monkeypatch.setattr(uvicorn, "__version__", "99.0.0")
    with pytest.raises(ValueError, match="require Uvicorn"):
        guarded_http_protocol(None, None)


def test_stale_header_callback_cannot_close_newer_phase():
    protocol = guarded_http_protocol(None, None)
    instance = object.__new__(protocol)
    instance.header_generation = 4
    instance.transport = SimpleNamespace(
        is_closing=lambda: False, close=lambda: pytest.fail("stale timer closed transport")
    )
    instance.expire_headers(3)


def test_parser_rejects_incomplete_oversize_and_non_http11_before_asgi():
    for request in (
        b"GET / HTTP/1.1\r\nHost: localhost\r\nX: " + b"x" * 17000,
        b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n",
    ):
        with listener() as server, connect(server) as sock:
            sock.sendall(request)
            assert b"400 Bad Request" in read_response(sock)
            assert server.counts["invalid_http"] == 1
            assert not server.entered.is_set()


def test_partial_bytes_preserve_one_timer_and_request_disarms_it_without_wall_clock_assertions():
    async def scenario():
        from uvicorn.server import ServerState

        closed = Event()

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        transport = SimpleNamespace(
            close=closed.set,
            is_closing=closed.is_set,
            write=lambda data: None,
            pause_reading=lambda: None,
            resume_reading=lambda: None,
            get_extra_info=lambda key, default=None: {
                "sockname": ("127.0.0.1", 8000),
                "peername": ("127.0.0.1", 40000),
            }.get(key, default),
        )
        protocol = guarded_http_protocol(
            SecuritySettings(), SimpleNamespace(transport=lambda event: None)
        )
        instance = protocol(
            uvicorn.Config(app, proxy_headers=False, ws="none", access_log=False), ServerState(), {}
        )
        instance.connection_made(transport)
        timer, generation = instance.header_timer, instance.header_generation
        for partial in (b"GET / HTTP/1.1\r\n", b"Host:", b" localhost"):
            instance.data_received(partial)
            assert instance.header_timer is timer and instance.header_generation == generation
        instance.data_received(b"\r\n\r\n")
        assert timer.cancelled() and instance.header_timer is None
        instance.connection_lost(None)
        await asyncio.gather(*instance.tasks)
        assert instance not in instance.connections

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "partial", [b"HTTP/1.1 200", b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\no"]
)
def test_response_helper_fails_on_eof_without_reading_again(partial):
    chunks = [partial, b""]

    def receive(size):
        assert chunks, "Helper tried reading again after EOF"
        return chunks.pop(0)

    with pytest.raises(EOFError, match="closed"):
        read_response(SimpleNamespace(recv=receive))


def test_pipelined_helper_fails_on_eof_after_first_response():
    chunks = [b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok", b""]

    def receive(size):
        assert chunks, "Pipelined helper tried reading again after EOF"
        return chunks.pop(0)

    with pytest.raises(EOFError):
        read_until(
            SimpleNamespace(recv=receive),
            lambda data: data.count(b"200 OK") >= 2 and data.endswith(b"ok"),
        )
