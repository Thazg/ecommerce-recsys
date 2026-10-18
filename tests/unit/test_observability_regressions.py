"""Startup outcome ownership, canonical sample labels and invalid scrape data."""

# ruff: noqa: E402

import asyncio
from threading import Event

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
from serving_test_support import TestClient
from serving_test_support import create_fixture_app as create_app
from test_observability import samples, total
from test_service_cache import Snapshot, application

from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.service import _PROCESS_PERMIT, State
from scripts.verify_service_observability import parse_metrics


@pytest.mark.parametrize("mode", ["stop", "double_cancel"])
@pytest.mark.parametrize("loader_fails", [False, True])
def test_owned_drain_records_exactly_one_startup_outcome(tmp_path, mode, loader_fails):
    async def scenario():
        entered, release = Event(), Event()

        def loader(*args, **kwargs):
            entered.set()
            assert release.wait(15)
            if loader_fails:
                raise ValueError("Injected load failure after termination request")
            return Snapshot()

        service = create_app(ServiceSettings(tmp_path, "a" * 64), loader=loader).state.service
        starting = asyncio.create_task(service.start())
        try:
            assert await asyncio.to_thread(entered.wait, 15)
            if mode == "double_cancel":
                starting.cancel()
                await asyncio.sleep(0)
                assert service.state == State.FAILED
                starting.cancel()
                await asyncio.gather(starting, return_exceptions=True)
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0)
            assert not stopping.done() and not service._startup_observed
            release.set()
            await asyncio.wait_for(asyncio.gather(starting, stopping, return_exceptions=True), 15)
            await service.stop()  # Repeat shutdown must not duplicate the observation.
            data = samples(service.telemetry.render(service))
            assert (
                total(
                    data,
                    "recsys_lifecycle_events_total",
                    event="startup_cancelled" if mode == "double_cancel" else "startup_stopped",
                )
                == 1
            )
            assert (
                sum(
                    value
                    for (name, labels), value in data.items()
                    if name == "recsys_lifecycle_events_total"
                    and dict(labels)["event"].startswith("startup_")
                )
                == 1
            )
            assert any(name == "recsys_startup_duration_seconds" for name, labels in data)
            assert total(data, "recsys_startup_duration_seconds") >= 0
            assert (
                service.state == State.STOPPED
                and service.bundle is service.identity is service.executor is None
            )
            assert _PROCESS_PERMIT.acquire(blocking=False)
            _PROCESS_PERMIT.release()
        finally:
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            await service.stop()

    asyncio.run(scenario())


def test_reordered_duplicate_label_sets_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_metrics('# TYPE metric counter\nmetric{a="1",b="2"} 1\nmetric{b="2",a="1"} 2\n')


def test_histogram_matching_ignores_label_order():
    data = parse_metrics(
        "# TYPE x histogram\n"
        'x_bucket{le="0.1",route="warm",cache="miss"} 1\n'
        'x_bucket{cache="miss",route="warm",le="+Inf"} 2\n'
        'x_sum{route="warm",cache="miss"} 0.3\n'
        'x_count{cache="miss",route="warm"} 2\n'
    )
    assert len(data) == 4
    assert all(labels == tuple(sorted(labels)) for name, labels in data)


@pytest.mark.parametrize(
    "snapshot",
    [
        {"entries": 2, "charged_bytes": 1},
        {"entries": 1, "charged_bytes": 10001},
        {"entries": 999, "charged_bytes": 999999},
        {"entries": -1, "charged_bytes": 1},
        {"entries": 1, "charged_bytes": True},
    ],
)
def test_invalid_cache_gauges_are_omitted_without_disabling_cache(tmp_path, monkeypatch, snapshot):
    app, _ = application(tmp_path, cache_max_entries=1, cache_max_bytes=10000)
    service = app.state.service
    with TestClient(app) as client:
        cache = service.cache
        monkeypatch.setattr(cache, "snapshot", lambda: snapshot)
        data = samples(client.get("/metrics").text)
        assert total(data, "recsys_cache_sample_success") == 0
        assert not any(
            name in {"recsys_cache_entries", "recsys_cache_charged_bytes"} for name, labels in data
        )
        assert total(data, "recsys_observer_errors_total") == 1
        assert service.cache is cache and service.cache_failures == 0
        assert client.post("/v1/recommendations", json={}).status_code == 200


def test_executor_setup_failure_has_one_startup_outcome(tmp_path, monkeypatch):
    from ecommerce_recsys.serving import service as service_module
    from ecommerce_recsys.serving.service import StartupFailed

    def fail(*args, **kwargs):
        raise OSError("Injected executor resource failure")

    monkeypatch.setattr(service_module, "ThreadPoolExecutor", fail)
    service = application(tmp_path)[0].state.service

    async def scenario():
        with pytest.raises(StartupFailed):
            await service.start()
        assert service.state == State.FAILED and service.executor is None
        data = samples(service.telemetry.render(service))
        assert total(data, "recsys_lifecycle_events_total", event="startup_failed") == 1
        assert any(name == "recsys_startup_duration_seconds" for name, labels in data)
        await service.stop()
        assert (
            total(
                samples(service.telemetry.render(service)),
                "recsys_lifecycle_events_total",
                event="startup_failed",
            )
            == 1
        )

    asyncio.run(scenario())
