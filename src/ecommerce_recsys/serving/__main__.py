"""Launch the supported local snapshot API with a single inference worker."""

from __future__ import annotations

import argparse
import os
from ipaddress import ip_address
from pathlib import Path

from ecommerce_recsys.serving.contracts import ServiceSettings
from ecommerce_recsys.serving.security import SecuritySettings


def loopback_host(value):
    if value == "localhost":
        return "127.0.0.1"
    try:
        if ip_address(value).is_loopback:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("The local launcher requires a loopback IP or localhost.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-path", type=Path, default=os.environ.get("RECSYS_BUNDLE_PATH"))
    parser.add_argument("--manifest-sha256", default=os.environ.get("RECSYS_MANIFEST_SHA256"))
    parser.add_argument("--host", type=loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--cache-max-entries", type=int, default=0)
    parser.add_argument("--cache-max-bytes", type=int, default=1048576)
    parser.add_argument("--cache-ttl-seconds", type=float, default=300.0)
    parser.add_argument("--busy-policy", choices=("reject", "recent_popularity"), default="reject")
    args = parser.parse_args()
    if args.bundle_path is None or args.manifest_sha256 is None or not 1 <= args.port <= 65535:
        parser.error("Provide --bundle-path, --manifest-sha256 and a port in 1-65535.")
    try:
        host_authority = f"[{args.host}]" if ":" in args.host else args.host
        security = SecuritySettings.from_environment(
            authorities=(f"{host_authority}:{args.port}", f"localhost:{args.port}")
        )
        settings = ServiceSettings(
            args.bundle_path,
            args.manifest_sha256,
            cache_max_entries=args.cache_max_entries,
            cache_max_bytes=args.cache_max_bytes,
            cache_ttl_seconds=args.cache_ttl_seconds,
            busy_policy=args.busy_policy,
        )
    except ValueError as error:
        parser.error(str(error))
    import uvicorn

    from ecommerce_recsys.serving.app import create_app
    from ecommerce_recsys.serving.http_protocol import guarded_http_protocol
    from ecommerce_recsys.serving.observability import configure_event_logging

    configure_event_logging()
    app = create_app(settings, security=security)
    protocol = guarded_http_protocol(security, app.state.service.telemetry)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
        loop="asyncio",
        http=protocol,
        ws="none",
        lifespan="on",
        timeout_keep_alive=5,
        proxy_headers=False,
        limit_concurrency=security.max_connections,
        backlog=64,
        h11_max_incomplete_event_size=security.header_limit,
    )


if __name__ == "__main__":
    main()
