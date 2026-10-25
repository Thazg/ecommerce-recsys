"""Run indexed snapshot inference on loopback for a local demonstration."""

from __future__ import annotations

import argparse
import asyncio
import os
import stat
import sys
import threading
from pathlib import Path


def watch_control_pipe(stream, stop_requested):
    """Notify the event-loop owner; pipe failure also requests an owned drain."""
    try:
        stream.readline(16)
    except (OSError, ValueError):
        pass
    finally:
        stop_requested.set()


async def serve_controlled(app, config, stop_requested):
    """Propagate pipe stop to the service while startup may still own a loader."""
    import uvicorn

    service = app.state.service

    class ControlledServer(uvicorn.Server):
        async def startup(self, sockets=None):
            if stop_requested.is_set():
                self.should_exit = True
                await service.stop()
                return
            try:
                await super().startup(sockets)
            except SystemExit:
                if not stop_requested.is_set():
                    raise
                self.should_exit = True

        def handle_exit(self, sig, frame):
            stop_requested.set()
            super().handle_exit(sig, frame)

    server = ControlledServer(config)

    async def control():
        await asyncio.to_thread(stop_requested.wait)
        server.should_exit = True
        # stop marks readiness false before awaiting the loader/worker drain.
        await service.stop()

    controller = asyncio.create_task(control())
    try:
        await server.serve()
    finally:
        stop_requested.set()
        controller.cancel()
        await asyncio.gather(controller, return_exceptions=True)
        await service.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--control-stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged local port in 1024-65535.")
    if args.control_stdin:
        try:
            valid = stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode)
        except (OSError, ValueError, AttributeError):
            valid = False
        if not valid:
            parser.error("Owned control requires an inherited stdin pipe.")
        stop_requested = threading.Event()

    # Set numerical initialization before importing model implementations.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"

    from ecommerce_recsys.serving.contracts import ServiceSettings
    from ecommerce_recsys.serving.security import SecuritySettings

    try:
        settings = ServiceSettings(args.bundle_path, args.manifest_sha256)
        security = SecuritySettings.from_environment(
            authorities=(f"127.0.0.1:{args.port}", f"localhost:{args.port}")
        )
    except ValueError as error:
        parser.error(str(error))

    import uvicorn

    from ecommerce_recsys.artifacts.compact_runtime import load_compact_bundle
    from ecommerce_recsys.serving.app import create_app
    from ecommerce_recsys.serving.http_protocol import guarded_http_protocol
    from ecommerce_recsys.serving.observability import configure_event_logging

    configure_event_logging()
    app = create_app(settings, security=security, loader=load_compact_bundle)
    options = dict(
        host="127.0.0.1",
        port=args.port,
        workers=1,
        access_log=False,
        loop="asyncio",
        http=guarded_http_protocol(security, app.state.service.telemetry),
        ws="none",
        lifespan="on",
        timeout_keep_alive=5,
        proxy_headers=False,
        limit_concurrency=security.max_connections,
        backlog=64,
        h11_max_incomplete_event_size=security.header_limit,
    )
    if args.control_stdin:
        # Import numerical DLLs before a Windows thread blocks on CRT stdin.
        # Model loading still belongs to the controlled lifespan below.
        threading.Thread(
            target=watch_control_pipe, args=(sys.stdin, stop_requested), daemon=True
        ).start()
        config = uvicorn.Config(app, **options)
        asyncio.run(
            serve_controlled(app, config, stop_requested), loop_factory=config.get_loop_factory()
        )
    else:
        uvicorn.run(app, **options)


if __name__ == "__main__":
    main()
