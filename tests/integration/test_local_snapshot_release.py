"""Fitted indexed API processes exercise the same private-pipe owner as real runs."""

import asyncio
import json
import socket
import threading
import time

from scripts.verify_local_release import OwnedServer


def test_fitted_indexed_http_parity_graceful_stop_restart_and_bad_pin(fitted_snapshot):
    bundle, pin, references, _, _ = fitted_snapshot
    manifest = json.loads((bundle / "model_manifest.json").read_text())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    for iteration in range(2):
        owner = OwnedServer(bundle, pin, port, time.monotonic() + 60)
        try:
            owner.start()
            for row in references:
                result = owner.probe.recommend(row, manifest, pin)
                assert result["status"] == 200 and result["prediction_sha256"]
                time.sleep(0.26)
            telemetry = owner.probe.reconcile()
            assert telemetry["primary_successes"] == len(references)
            assert owner.sampler.summary(owner.ready_at, time.monotonic())["sample_count"] > 2
            if iteration == 1:
                # Parent pipe EOF follows the same application drain as an explicit stop.
                owner.child.stdin.close()
            stopped = owner.stop(graceful=True)
            assert 0 < stopped.pop("stop_seconds") < 20
            assert stopped == {
                "exit_code": 0,
                "forced": False,
                "listener_closed": True,
                "cleanup_events": 1,
                "startup_ready_events": 1,
            }
        finally:
            if owner.needs_cleanup():
                owner.stop()
    invalid = OwnedServer(bundle, "0" * 64, port, time.monotonic() + 45)
    try:
        invalid.start(expect_ready=False)
        invalid.child.wait(timeout=30)
        result = invalid.stop()
        assert result["exit_code"] != 0 and result["listener_closed"]
        assert result["startup_ready_events"] == 0 and not result["forced"]
    finally:
        if invalid.needs_cleanup():
            invalid.stop()


def test_fitted_control_eof_before_startup_never_publishes_ready(fitted_snapshot):
    bundle, pin, _, _, _ = fitted_snapshot
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    owner = OwnedServer(bundle, pin, port, time.monotonic() + 45)
    try:
        owner.start(expect_ready=False)
        owner.child.stdin.close()
        result = owner.stop(graceful=True)
        assert result["startup_ready_events"] == 0 and result["cleanup_events"] == 1
        assert result["exit_code"] == 0 and not result["forced"]
        assert not owner.needs_cleanup()
    finally:
        if owner.needs_cleanup():
            owner.stop()


def test_fitted_control_stop_during_load_drains_without_late_readiness(fitted_snapshot):
    import uvicorn

    from ecommerce_recsys.artifacts.compact_runtime import load_compact_bundle
    from ecommerce_recsys.serving.app import create_app
    from ecommerce_recsys.serving.contracts import ServiceSettings
    from scripts.serve_local_snapshot import serve_controlled

    bundle, pin, _, _, _ = fitted_snapshot
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()

    def delayed_loader(*args, **kwargs):
        loaded = load_compact_bundle(*args, **kwargs)
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("Fixture loader release timed out.")
        return loaded

    app = create_app(ServiceSettings(bundle, pin), loader=delayed_loader)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        loop="asyncio",
        lifespan="on",
        access_log=False,
        proxy_headers=False,
    )

    async def exercise():
        task = asyncio.create_task(serve_controlled(app, config, stop))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            stop.set()
            # Wait for the service stop transition before completing its owned loader.
            for _ in range(100):
                if app.state.service.state.value == "stopped":
                    break
                await asyncio.sleep(0.01)
            assert app.state.service.state.value == "stopped"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=10)

    asyncio.run(exercise())
    assert app.state.service._startup_outcome == "startup_stopped"
    assert app.state.service.bundle is None and app.state.service.executor is None
