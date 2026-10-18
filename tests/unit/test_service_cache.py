"""Result reuse and explicit overload behavior at the HTTP/service boundary."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
import httpx2 as httpx
from fastapi.testclient import TestClient

from ecommerce_recsys.artifacts import Recommendation
from ecommerce_recsys.retrieval.popularity_retriever import PopularityRetriever
from ecommerce_recsys.serving.app import create_app
from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.service import StartupFailed, State


class Snapshot:
    def __init__(self):
        self.items = tuple(f"item{i:02}" for i in range(30))
        self.user_index = {"known": 0, "other": 1, "exhausted": 2}
        self.manifest = {"bundle_version": "fixture", "snapshot": {"cutoff": 99}}
        self.cold = PopularityRetriever(pd.DataFrame({"item_id": self.items}), self.items)
        self.cold.name = "recent_popularity"  # Fixture shares the real direct-source filtering.
        self.entered, self.release = Event(), Event()
        self.release.set()
        self.blocking = self.fail = False
        self.calls = []

    def context(self, user_id):
        history = (
            self.items
            if user_id == "exhausted"
            else self.items[:2]
            if user_id in self.user_index
            else ()
        )
        return SimpleNamespace(history=history)

    def recommend(self, user_id=None, *, k=20):
        self.calls.append((user_id, k))
        if self.blocking:
            self.entered.set()
            if not self.release.wait(60):
                raise TimeoutError("Test worker not released")
        if self.fail:
            raise ValueError("Fixture model failure")
        seen = set(self.context(user_id).history)
        return Recommendation(
            tuple(item for item in self.items if item not in seen)[:k],
            "hybrid_learned" if user_id in self.user_index else "recent_popularity",
            "fixture",
            99,
        )


def application(tmp_path, **options):
    snapshot = Snapshot()
    settings = ServiceSettings(tmp_path, "a" * 64, **options)
    return create_app(settings, loader=lambda *a, **k: snapshot), snapshot


def test_cache_reuses_top_twenty_prefix_and_canonical_cold_context(tmp_path):
    app, model = application(tmp_path, cache_max_entries=8)
    with TestClient(app) as client:
        first = client.post("/v1/recommendations", json={"user_id": "known", "k": 5}).json()
        second = client.post("/v1/recommendations", json={"user_id": "known", "k": 20}).json()
        assert first["cache_status"] == "miss" and second["cache_status"] == "hit"
        assert first["items"] == second["items"][:5]
        assert first["request_id"] != second["request_id"] and model.calls[-1] == ("known", 20)
        assert not second["degraded"] and second["manifest_sha256"] == "a" * 64
        assert (
            client.post("/v1/recommendations", json={"user_id": "unknown-a"}).json()["cache_status"]
            == "miss"
        )
        for user in ("unknown-b", None):
            assert (
                client.post("/v1/recommendations", json={"user_id": user}).json()["cache_status"]
                == "hit"
            )
        state = client.get("/health/ready").json()
        assert state["primary_calls"] == 2 and state["cache"]["entries"] == 2
        assert state["cache"]["hits"] == 3


@pytest.mark.parametrize("failure", ["read", "write", "corrupt", "stats", "invalid_stats"])
def test_cache_failure_disables_only_cache(tmp_path, monkeypatch, failure):
    app, _ = application(tmp_path, cache_max_entries=8)
    with TestClient(app) as client:
        cache = app.state.service.cache

        def fail(*a):
            raise RuntimeError("Cache unavailable")

        if failure == "invalid_stats":
            monkeypatch.setattr(cache, "snapshot", lambda: {})
        elif failure == "corrupt":
            monkeypatch.setattr(
                cache,
                "get",
                lambda *a: Recommendation(("outside",), "hybrid_learned", "fixture", 99),
            )
        else:
            monkeypatch.setattr(
                cache, {"read": "get", "write": "put", "stats": "snapshot"}[failure], fail
            )
        if failure in ("stats", "invalid_stats"):
            assert client.get("/health/ready").status_code == 200
        result = client.post("/v1/recommendations", json={"user_id": "known"})
        assert result.status_code == 200 and result.json()["cache_status"] == "bypass"
        assert not result.json()["degraded"]
        status = client.get("/health/ready").json()
        assert status["state"] == "ready" and not status["cache"]["enabled"]
        assert status["cache"]["failures"] == 1


def test_expiry_and_empty_outputs_are_cached_without_padding(tmp_path):
    app, _ = application(tmp_path, cache_max_entries=1, cache_ttl_seconds=5)
    with TestClient(app) as client:
        now = [10.0]
        app.state.service.cache._clock = lambda: now[0]
        for status in ("miss", "hit"):
            result = client.post("/v1/recommendations", json={"user_id": "exhausted"}).json()
            assert result["cache_status"] == status and result["items"] == []
        now[0] = 15.0
        assert (
            client.post("/v1/recommendations", json={"user_id": "exhausted"}).json()["cache_status"]
            == "miss"
        )
        assert client.get("/health/ready").json()["cache"]["expirations"] == 1


def test_shutdown_does_not_serve_hits_or_keep_late_worker_cache(tmp_path):
    async def scenario():
        app, model = application(tmp_path, cache_max_entries=8, busy_policy="recent_popularity")
        service = app.state.service
        async with app.router.lifespan_context(app):
            await service.recommend("known", 20, "prime")
            model.blocking = True
            model.release.clear()
            pending = asyncio.create_task(service.recommend("other", 20, "active"))
            try:
                assert await asyncio.to_thread(model.entered.wait, 15)
                stopped = asyncio.create_task(service.stop())
                await asyncio.sleep(0)
                from ecommerce_recsys.serving.service import NotReady

                with pytest.raises(NotReady):
                    await service.recommend("known", 20, "after-stop")
                assert not stopped.done()
            finally:
                model.release.set()
            await asyncio.wait_for(pending, 15)
            await asyncio.wait_for(stopped, 15)
        assert service.cache is None and service.fallback_pool == ()

    asyncio.run(scenario())


def test_primary_failure_invalidates_cache_and_never_degrades(tmp_path):
    app, model = application(tmp_path, cache_max_entries=8, busy_policy="recent_popularity")
    with TestClient(app) as client:
        assert client.post("/v1/recommendations", json={"user_id": "known"}).status_code == 200
        model.fail = True
        assert client.post("/v1/recommendations", json={"user_id": "other"}).status_code == 500
        assert client.post("/v1/recommendations", json={"user_id": "known"}).status_code == 503
        assert client.get("/health/ready").json()["cache"]["enabled"] is False
        assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("busy_policy", ["reject", "recent_popularity"])
def test_busy_hits_misses_cancellation_and_no_fallback_cache_pollution(tmp_path, busy_policy):
    async def scenario():
        app, model = application(tmp_path, cache_max_entries=8, busy_policy=busy_policy)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/v1/recommendations", json={"user_id": "known"})
                model.blocking = True
                model.release.clear()
                pending = asyncio.create_task(
                    client.post("/v1/recommendations", json={"user_id": "other"})
                )
                try:
                    assert await asyncio.to_thread(model.entered.wait, 15)
                    hit = await asyncio.wait_for(
                        client.post("/v1/recommendations", json={"user_id": "known"}), 15
                    )
                    assert hit.json()["cache_status"] == "hit" and not hit.json()["degraded"]
                    for user in ("other", "exhausted", None):
                        answer = await client.post("/v1/recommendations", json={"user_id": user})
                        if busy_policy == "reject":
                            assert (
                                answer.status_code == 503 and answer.headers["retry-after"] == "1"
                            )
                        else:
                            data = answer.json()
                            assert (
                                data["route"] == "recent_popularity_fallback"
                                and data["degraded_reason"] == "busy"
                            )
                            assert data["cache_status"] == "bypass" and data["degraded"] is True
                            expected = [
                                item
                                for item in model.items
                                if item not in model.context(user).history
                            ][:20]
                            assert data["items"] == expected
                    assert (await client.get("/health/ready")).status_code == 200
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    blocked = await client.post("/v1/recommendations", json={"user_id": "other"})
                    assert blocked.status_code == (503 if busy_policy == "reject" else 200)
                finally:
                    model.release.set()
                # Queue a no-op on the same executor to establish completion, without timing sleeps.
                await asyncio.get_running_loop().run_in_executor(
                    app.state.service.executor, lambda: None
                )
                completed = await client.post("/v1/recommendations", json={"user_id": "other"})
                assert (
                    completed.json()["cache_status"] == "hit" and not completed.json()["degraded"]
                )
                assert app.state.service.primary_calls == 2
        assert app.state.service.cache is None and app.state.service.fallback_pool == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "config",
    [
        {"cache_max_entries": True},
        {"cache_max_bytes": 0},
        {"cache_ttl_seconds": float("nan")},
        {"busy_policy": "hidden"},
    ],
)
def test_settings_reject_invalid_cache_or_busy_policy(tmp_path, config):
    with pytest.raises(ValueError):
        ServiceSettings(tmp_path, "a" * 64, **config)


def test_invalid_prepared_fallback_aborts_startup(tmp_path):
    app, model = application(tmp_path, busy_policy="recent_popularity")
    model.cold.generate = lambda *a: [SimpleNamespace(item_id="outside")]
    with pytest.raises(StartupFailed):
        with TestClient(app):
            pass
    assert app.state.service.state == State.FAILED
    assert app.state.service.cache is None and app.state.service.fallback_pool == ()
