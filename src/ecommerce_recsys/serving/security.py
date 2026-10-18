"""Immutable local exposure policy and secret-safe operator configuration."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field, fields
from ipaddress import ip_address
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit


def authority(value):
    """Parse an exact HTTP authority, without DNS, userinfo or normalization gaps."""
    if type(value) is not str or not re.fullmatch(
        r"(?:localhost|[0-9.]+|\[[0-9a-fA-F:.]+\])(?::[0-9]+)?", value, re.IGNORECASE
    ):
        raise ValueError("Invalid local authority.")
    try:
        value.encode("ascii")
        parsed = urlsplit("http://" + value)
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else 80
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not host
            or value.endswith(":")
            or "%" in value
            or "\\" in value
        ):
            raise ValueError
        if host == "localhost":
            normalized = host
        else:
            address = ip_address(host)
            if not address.is_loopback:
                raise ValueError
            normalized = address.compressed
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("Invalid local authority.") from None
    return normalized, port


@dataclass(frozen=True, slots=True)
class SecuritySettings:
    authorities: tuple[str, ...] = ("127.0.0.1:8000", "localhost:8000", "[::1]:8000")
    body_timeout_seconds: float = 5.0
    body_readers: int = 8
    global_rate: float = 10.0
    global_burst: int = 20
    peer_rate: float = 5.0
    peer_burst: int = 10
    peer_entries: int = 128
    peer_ttl_seconds: float = 300.0
    max_connections: int = 32
    header_timeout_seconds: float = 5.0
    header_limit: int = 16384
    target_limit: int = 8192
    token: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.authorities) is not tuple or not 1 <= len(self.authorities) <= 8:
            raise ValueError("Configure one to eight explicit local authorities.")
        for value in self.authorities:
            authority(value)
        for name, maximum in (
            ("body_readers", 64),
            ("global_burst", 1000),
            ("peer_burst", 1000),
            ("peer_entries", 4096),
            ("max_connections", 256),
            ("header_limit", 65536),
            ("target_limit", 16384),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"Invalid hardening setting: {name}.")
        for name, maximum in (
            ("body_timeout_seconds", 60),
            ("header_timeout_seconds", 60),
            ("global_rate", 1000),
            ("peer_rate", 1000),
            ("peer_ttl_seconds", 3600),
        ):
            value = getattr(self, name)
            minimum = 0.001 if name in {"global_rate", "peer_rate"} else 0.01
            if (
                type(value) not in (int, float)
                or not minimum <= value <= maximum
                or not isfinite(value)
            ):
                raise ValueError(f"Invalid hardening setting: {name}.")
        if self.peer_ttl_seconds < self.peer_burst / self.peer_rate:
            raise ValueError("Peer TTL must cover the full refill period.")
        if self.token is not None and (
            type(self.token) is not bytes
            or not 32 <= len(self.token) <= 256
            or any(c < 33 or c > 126 for c in self.token)
        ):
            raise ValueError("API token must contain 32-256 printable non-whitespace ASCII bytes.")

    def public_policy(self):
        return {
            **{f.name: getattr(self, f.name) for f in fields(self) if f.name != "token"},
            "authentication": "bearer" if self.token is not None else "local_anonymous",
            "body_limit": 8192,
            "request_trailers": "reject",
            "proxy_headers": False,
            "backlog": 64,
            "keep_alive_seconds": 5,
        }

    @classmethod
    def from_environment(cls, *, authorities):
        token = os.environ.get("RECSYS_API_TOKEN")
        file = os.environ.get("RECSYS_API_TOKEN_FILE")
        if token is not None and file is not None:
            raise ValueError("Configure only one API token source.")
        try:
            if file is not None:
                with Path(file).open("rb") as stream:
                    raw = stream.read(259)
                if raw.endswith(b"\r\n"):
                    raw = raw[:-2]
                elif raw.endswith(b"\n"):
                    raw = raw[:-1]
            else:
                raw = token.encode("ascii") if token is not None else None
        except (OSError, ValueError, UnicodeError):
            raise ValueError("API token configuration could not be read.") from None
        return cls(authorities=authorities, token=raw)

    def authenticated(self, values):
        if self.token is None:
            return True
        if len(values) != 1:
            return False
        scheme, separator, candidate = values[0].partition(b" ")
        return (
            scheme.lower() == b"bearer"
            and separator == b" "
            and 32 <= len(candidate) <= 256
            and secrets.compare_digest(candidate, self.token)
        )

    def valid_host(self, value):
        try:
            actual = authority(value.decode("ascii"))
            return actual in tuple(authority(item) for item in self.authorities)
        except (ValueError, UnicodeError):
            return False

    def valid_origin(self, value, host):
        try:
            parsed = urlsplit(value.decode("ascii"))
            return (
                parsed.scheme == "http"
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and bool(parsed.netloc)
                and authority(parsed.netloc) == authority(host.decode("ascii"))
                and value == ("http://" + parsed.netloc).encode("ascii")
            )
        except (ValueError, UnicodeError):
            return False
