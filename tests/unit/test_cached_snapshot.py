"""Actually fitted snapshot parity through caching and the prepared direct source."""

# ruff: noqa: E402

import http.client
import json
import socket
import time
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
from serving_test_support import TestClient
from serving_test_support import create_fixture_app as create_app
from test_http_protocol_guards import listener

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.contract import file_sha
from ecommerce_recsys.artifacts.export import export_bundle
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import SnapshotFeatures
from ecommerce_recsys.serving.app import create_app as hardened_app
from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.security import SecuritySettings
from ecommerce_recsys.serving.service import _PROCESS_PERMIT
from scripts.benchmark_ranker import build_sources


@single_thread_benchmark
def test_real_snapshot_cached_prefixes_and_seen_filtered_fallback(tmp_path):
    train = pd.DataFrame(
        [(f"u{u}", f"i{i}", 100 + i, "view") for u in range(12) for i in range(10) if (u + i) % 3],
        columns=["user_id", "item_id", "timestamp", "event_type"],
    )
    catalog = pd.DataFrame(
        {"item_id": [f"i{i}" for i in range(10)], "category_id": [None, "a"] * 5}
    )
    configs = {
        "als": {"factors": 3, "iterations": 2, "regularization": 0.01},
        "item_knn": {"shrinkage_lambda": 100.0},
    }
    sources, _, _, _ = build_sources(train, catalog, 150, configs)
    path = export_bundle(
        tmp_path,
        "http-cache-fixture",
        sources=sources,
        features=SnapshotFeatures.from_frames(train, catalog, 150),
        weights=np.linspace(-0.1, 0.2, 32),
        scales=np.ones(32),
        snapshot={
            "fold_index": 9,
            "cutoff": 150,
            "ranker_label_cutoff": 100,
            "users": 12,
            "items": 10,
            "events": len(train),
            "configs": configs,
            "seeds": {"als_fit": 42, "ranker_negative_sampling": 42},
        },
        provenance={"test": "actual fitted retrieval sources"},
        references=[],
    )
    bundle = load_bundle(path)
    expected = bundle.recommend("u0").items
    context = bundle.context("u1")
    fallback = [row.item_id for row in bundle.cold.generate(context, 20)]
    app = create_app(
        ServiceSettings(
            path,
            file_sha(path / "model_manifest.json"),
            cache_max_entries=8,
            busy_policy="recent_popularity",
        )
    )
    with TestClient(app) as client:
        for k, status in ((1, "miss"), (20, "hit"), (5, "hit")):
            result = client.post("/v1/recommendations", json={"user_id": "u0", "k": k}).json()
            assert result["cache_status"] == status and tuple(result["items"]) == expected[:k]
        assert _PROCESS_PERMIT.acquire(blocking=False)
        try:
            data = client.post("/v1/recommendations", json={"user_id": "u1"}).json()
        finally:
            _PROCESS_PERMIT.release()
        assert data["items"] == fallback and data["degraded"]
        assert not set(data["items"]).intersection(context.history)
        normal = client.post("/v1/recommendations", json={"user_id": "u1"}).json()
        assert normal["cache_status"] == "miss" and not normal["degraded"]

    # The same actually fitted snapshot crosses real TCP, h11 and ASGI. A short
    # explicit test deadline keeps fault probes quick; production remains 5s.
    security = replace(SecuritySettings(), body_timeout_seconds=2.0, body_readers=2)
    actual = hardened_app(
        ServiceSettings(path, file_sha(path / "model_manifest.json"), cache_max_entries=8),
        security=security,
    )
    with listener(app=actual, lifespan="on", header_timeout_seconds=0.15) as server:
        with socket.create_connection(("127.0.0.1", server.port), timeout=10) as sock:
            sock.sendall(
                b"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{"
            )
            # Header timer is already disarmed; the ASGI body deadline owns this phase.
            time.sleep(0.2)
            response = http.client.HTTPResponse(sock)
            response.begin()
            assert response.status == 408
            assert json.loads(response.read())["error"]["code"] == "body_timeout"
            assert response.getheader("Connection") == "close"
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
        try:
            for k in (20, 5):
                connection.request(
                    "POST",
                    "/v1/recommendations",
                    json.dumps({"user_id": "u0", "k": k}),
                    headers={"Host": "127.0.0.1:8000", "Content-Type": "application/json"},
                )
                response = connection.getresponse()
                result = json.loads(response.read())
                assert response.status == 200 and tuple(result["items"]) == expected[:k]
            assert actual.state.request_admission.readers == 0
            assert actual.state.service.readiness()[1]
            assert not server.counts  # The shorter header deadline did not cut off a body.
        finally:
            connection.close()

        readers = []
        try:
            calls = actual.state.service.primary_calls
            prefix = (
                b"POST /v1/recommendations HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n"
                b"Content-Type: application/json\r\nContent-Length: 20\r\n\r\n{"
            )
            for _ in range(2):
                reader = socket.create_connection(("127.0.0.1", server.port), timeout=10)
                reader.sendall(prefix)
                readers.append(reader)
            deadline = time.monotonic() + 10
            while actual.state.request_admission.readers != 2:
                assert time.monotonic() < deadline
                time.sleep(0.005)
            with socket.create_connection(("127.0.0.1", server.port), timeout=10) as overflow:
                overflow.sendall(prefix)
                response = http.client.HTTPResponse(overflow)
                response.begin()
                assert response.status == 503
                assert json.loads(response.read())["error"]["code"] == "request_overloaded"
            assert actual.state.service.primary_calls == calls
        finally:
            for reader in readers:
                reader.close()
        deadline = time.monotonic() + 10
        while actual.state.request_admission.readers:
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert actual.state.service.readiness()[1]
