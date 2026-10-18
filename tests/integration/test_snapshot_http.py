"""Fitted synthetic models through the actual launcher in a child process."""

import json
import os
import shutil
import socket

import pytest
from service_process import SnapshotServer

from ecommerce_recsys.artifacts import load_bundle


@pytest.mark.parametrize("enabled", [False, True], ids=["anonymous-off", "bearer-cache"])
def test_fitted_snapshot_requests_cache_and_eligibility(fitted_snapshot, tmp_path, enabled):
    path, pin, references, train, catalog = fitted_snapshot
    # Package reference is independently checked against the producer's full trace.
    package = load_bundle(path, expected_manifest_sha256=pin)
    for row in references:
        assert package.trace(row["user_id"]) == row["trace"]
    expected = {row["user_id"]: row["trace"] for row in references}
    ids = set()
    with SnapshotServer(
        path, pin, tmp_path / "http.log", cached=enabled, authenticated=enabled
    ) as server:
        pid = server.process.pid
        with pytest.raises(RuntimeError, match="already started"):
            server.start()
        assert server.process.pid == pid
        for user in ("u00", "exhausted", None):
            seen = set(train.loc[train["user_id"] == user, "item_id"])
            for position, k in enumerate((1, 5, 10, 20)):
                body, headers = server.call(
                    "POST", "/v1/recommendations", {"user_id": user, "k": k}
                )
                assert body["items"] == expected[user]["output"][:k]
                assert body["route"] == expected[user]["route"]
                assert body["manifest_sha256"] == pin and not body["degraded"]
                expected_cache = ("miss" if position == 0 else "hit") if enabled else "disabled"
                assert body["cache_status"] == expected_cache
                assert set(body["items"]) <= set(catalog["item_id"])
                assert not seen.intersection(body["items"])
                assert (
                    body["request_id"] not in ids and headers["x-request-id"] == body["request_id"]
                )
                assert headers["cache-control"] == "no-store"
                ids.add(body["request_id"])
        unknown, _ = server.call("POST", "/v1/recommendations", {"user_id": "unknown-context"})
        assert unknown["items"] == expected[None]["output"]
        assert unknown["cache_status"] == ("hit" if enabled else "disabled")
        ready, _ = server.call("GET", "/health/ready")
        assert ready["primary_calls"] == (3 if enabled else 13)
        assert ready["cache"]["entries"] == (3 if enabled else 0)


def test_access_and_validation_denials_preserve_the_fitted_service(fitted_snapshot, tmp_path):
    path, pin, _, _, _ = fitted_snapshot
    with SnapshotServer(path, pin, tmp_path / "denials.log", authenticated=True) as server:
        for value, status, code, options in (
            ({}, 401, "unauthorized", {"credential": False}),
            ({}, 403, "forbidden_origin", {"headers": {"Origin": "null"}}),
            ({"k": True}, 422, "validation_error", {}),
            (b'{"k":1,"k":2}', 400, "invalid_json", {}),
            (b"x" * 8193, 413, "body_too_large", {}),
        ):
            result, _ = server.call(
                "POST", "/v1/recommendations", value, expected=status, **options
            )
            assert result["error"]["code"] == code
        ready, _ = server.call("GET", "/health/ready")
        assert ready["state"] == "ready" and ready["primary_calls"] == 0
        result, _ = server.call("POST", "/v1/recommendations", {"user_id": "u00"})
        assert result["route"] == "hybrid_learned" and not result["degraded"]
        schema, _ = server.call("GET", "/openapi.json")
        assert schema["info"]["version"] == "1.2.0"
        assert "BearerAuth" in schema["components"]["securitySchemes"]
        assert server.token not in server.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["pin", "corrupt", "missing"])
def test_bad_snapshot_cannot_open_a_ready_listener(fitted_snapshot, tmp_path, failure):
    path, pin, _, _, _ = fitted_snapshot
    if failure != "pin":
        path = shutil.copytree(path, tmp_path / "invalid-bundle")
        component = path / "weights.npy"
        if failure == "missing":
            component.unlink()
        else:
            with component.open("ab") as stream:
                stream.write(b"tampered")
    else:
        pin = "0" * 64
    server = SnapshotServer(path, pin, tmp_path / "startup.log")
    try:
        server.start(ready=False)
        assert server.process.wait(timeout=30) != 0
        with socket.socket() as sock:
            sock.settimeout(1)
            assert sock.connect_ex(("127.0.0.1", server.port)) != 0
    finally:
        server.stop()


def test_owned_process_stop_releases_listener_and_snapshot_restarts(fitted_snapshot, tmp_path):
    path, pin, references, _, _ = fitted_snapshot
    expected = next(row["trace"]["output"] for row in references if row["user_id"] == "u00")
    server = SnapshotServer(path, pin, tmp_path / "stopped.log").start()
    try:
        result, _ = server.call("POST", "/v1/recommendations", {"user_id": "u00"})
        assert result["items"] == expected
        # Windows background children have no console for CTRL_BREAK delivery.
        # There we assert stop/restart only; owned drain has event-controlled unit coverage.
        server.stop(graceful=os.name != "nt")
        with socket.socket() as sock:
            sock.settimeout(1)
            assert sock.connect_ex(("127.0.0.1", server.port)) != 0
        if os.name != "nt":
            events = [
                json.loads(line)
                for line in server.log_path.read_text().splitlines()
                if line.startswith('{"event":')
            ]
            assert sum(row["event"] == "cleanup_complete" for row in events) == 1
        with SnapshotServer(path, pin, tmp_path / "restarted.log") as restarted:
            result, _ = restarted.call("POST", "/v1/recommendations", {"user_id": "u00"})
            assert result["items"] == expected
    finally:
        server.stop()
