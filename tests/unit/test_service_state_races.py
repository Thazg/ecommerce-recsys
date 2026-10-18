"""Deterministic admission, startup/shutdown and fallback fault interleavings."""

# ruff: noqa: E402

import asyncio
from threading import Event

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
import httpx2 as httpx
from serving_test_support import create_fixture_app as create_app
from test_service_cache import Snapshot, application

from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.service import _PROCESS_PERMIT, StartupFailed, State


def test_primary_failure_during_lookup_cannot_admit_another_model_call(tmp_path, monkeypatch):
    async def scenario():
        app, model = application(tmp_path, cache_max_entries=8)
        service = app.state.service
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                finished = Event()
                execute = service._execute

                def observed_execute(*args):
                    try:
                        return execute(*args)
                    finally:
                        finished.set()

                monkeypatch.setattr(service, "_execute", observed_execute)
                model.blocking = model.fail = True
                model.release.clear()
                pending = asyncio.create_task(
                    client.post("/v1/recommendations", json={"user_id": "known"})
                )
                try:
                    assert await asyncio.to_thread(model.entered.wait, 15)
                    cache_get = service.cache.get

                    def lookup(user):
                        model.release.set()
                        assert finished.wait(15)
                        assert service.state == State.FAILED
                        model.fail = model.blocking = False
                        return cache_get(user)

                    monkeypatch.setattr(service.cache, "get", lookup)
                    rejected = await client.post("/v1/recommendations", json={"user_id": "other"})
                    assert (
                        rejected.status_code == 503
                        and rejected.json()["error"]["code"] == "not_ready"
                    )
                    assert (await pending).status_code == 500
                    assert service.primary_calls == 1 and service.state == State.FAILED
                    assert (await client.get("/health/ready")).status_code == 503
                    assert _PROCESS_PERMIT.acquire(blocking=False)
                    _PROCESS_PERMIT.release()
                finally:
                    model.release.set()
                    await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_start", [False, True])
@pytest.mark.parametrize("loader_fails", [False, True])
def test_stop_while_loading_never_publishes_ready(tmp_path, cancel_start, loader_fails):
    async def scenario():
        entered, release = Event(), Event()

        def loader(*args, **kwargs):
            entered.set()
            assert release.wait(15)
            if loader_fails:
                raise ValueError("Injected loader failure")
            return Snapshot()

        app = create_app(
            ServiceSettings(
                tmp_path, "a" * 64, cache_max_entries=8, busy_policy="recent_popularity"
            ),
            loader=loader,
        )
        service = app.state.service
        starting = asyncio.create_task(service.start())
        try:
            assert await asyncio.to_thread(entered.wait, 15)
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0)
            assert service.state == State.STOPPED
            if cancel_start:
                starting.cancel()
            release.set()
            results = await asyncio.wait_for(
                asyncio.gather(starting, stopping, return_exceptions=True), 15
            )
            assert isinstance(results[0], (StartupFailed, asyncio.CancelledError))
            assert results[1] is None
            assert service.state == State.STOPPED
            assert service.bundle is service.identity is service.executor is service.cache is None
            assert service.fallback_pool == ()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                ready = await client.get("/health/ready")
                assert ready.status_code == 503 and ready.json()["state"] == "stopped"
                assert (await client.post("/v1/recommendations", json={})).status_code == 503
            assert _PROCESS_PERMIT.acquire(blocking=False)
            _PROCESS_PERMIT.release()
        finally:
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            await service.stop()

    asyncio.run(scenario())


def test_cancelled_startup_keeps_cleanup_owned_until_worker_exits(tmp_path):
    async def scenario():
        entered, release = Event(), Event()

        def loader(*args, **kwargs):
            entered.set()
            assert release.wait(15)
            return Snapshot()

        service = create_app(
            ServiceSettings(tmp_path, "a" * 64, cache_max_entries=8), loader=loader
        ).state.service
        starting = asyncio.create_task(service.start())
        try:
            assert await asyncio.to_thread(entered.wait, 15)
            starting.cancel()
            await asyncio.sleep(0)
            assert service.state == State.FAILED
            starting.cancel()  # A second cancellation cannot cancel the owned drain.
            await asyncio.gather(starting, return_exceptions=True)
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0)
            assert not stopping.done()
            release.set()
            await asyncio.wait_for(stopping, 15)
            assert service.bundle is service.executor is service.cache is None
            assert service.state == State.STOPPED
        finally:
            release.set()
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["context", "catalog", "duplicate"])
def test_fallback_snapshot_fault_invalidates_state_without_releasing_primary_permit(
    tmp_path, monkeypatch, fault
):
    async def scenario():
        app, model = application(tmp_path, cache_max_entries=8, busy_policy="recent_popularity")
        service = app.state.service
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
            ) as client:
                await client.post("/v1/recommendations", json={"user_id": "known"})
                model.blocking = True
                model.release.clear()
                pending = asyncio.create_task(
                    client.post("/v1/recommendations", json={"user_id": "other"})
                )
                try:
                    assert await asyncio.to_thread(model.entered.wait, 15)
                    context = model.context

                    def broken_context(user):
                        if user is None:
                            raise ValueError("Injected fallback snapshot error")
                        return context(user)

                    if fault == "context":
                        monkeypatch.setattr(model, "context", broken_context)
                    elif fault == "catalog":
                        service.fallback_pool = ("outside",)
                    else:
                        service.fallback_pool = (model.items[0], model.items[0])
                    failed = await client.post("/v1/recommendations", json={})
                    assert (
                        failed.status_code == 500
                        and failed.json()["error"]["code"] == "inference_failed"
                    )
                    assert service.state == State.FAILED and service.cache is None
                    assert service.fallback_pool == () and service.fallback_calls == 0
                    assert (await client.get("/health/ready")).status_code == 503
                    assert (await client.get("/health/live")).status_code == 200
                    assert (
                        await client.post("/v1/recommendations", json={"user_id": "known"})
                    ).status_code == 503
                    assert not _PROCESS_PERMIT.acquire(blocking=False)
                finally:
                    model.release.set()
                assert (await asyncio.wait_for(pending, 15)).status_code == 503
                assert service.primary_calls == 2
                assert _PROCESS_PERMIT.acquire(blocking=False)
                _PROCESS_PERMIT.release()

    asyncio.run(scenario())
