"""Owned child launcher with bounded startup, requests and cross-platform exit."""

from __future__ import annotations

import http.client
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SnapshotServer:
    def __init__(self, bundle, pin, log_path, *, cached=False, authenticated=False):
        self.bundle, self.pin, self.log_path = bundle, pin, log_path
        self.cached = cached
        self.token = secrets.token_urlsafe(32) if authenticated else None
        self.process = self.log = None
        self.last_attempt = 0.0
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]

    def start(self, *, ready=True):
        if self.process is not None:
            raise RuntimeError("Snapshot process owner has already started; create a new owner.")
        env = os.environ.copy()
        for name in (
            "RECSYS_API_TOKEN",
            "RECSYS_API_TOKEN_FILE",
            "RECSYS_BUNDLE_PATH",
            "RECSYS_MANIFEST_SHA256",
        ):
            env.pop(name, None)
        if self.token:
            env["RECSYS_API_TOKEN"] = self.token
        command = [
            sys.executable,
            "-m",
            "ecommerce_recsys.serving",
            "--bundle-path",
            str(self.bundle),
            "--manifest-sha256",
            self.pin,
            "--port",
            str(self.port),
        ]
        if self.cached:
            command += ["--cache-max-entries", "64"]
        self.log = self.log_path.open("wb")
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=self.log,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0,
            )
            if not ready:
                return self
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("Fixture service exited before readiness.")
                try:
                    self.call("GET", "/health/ready")
                    return self
                except OSError:
                    time.sleep(0.05)
            raise TimeoutError("Fixture readiness deadline exceeded.")
        except BaseException:
            self.stop()
            raise

    def call(self, method, path, body=None, *, expected=200, headers=None, credential=True):
        if method == "POST":
            time.sleep(max(0, 0.26 - (time.monotonic() - self.last_attempt)))
            self.last_attempt = time.monotonic()
        fields = {"Content-Type": "application/json"}
        if self.token and credential:
            fields["Authorization"] = "Bearer " + self.token
        fields.update(headers or {})
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body, fields)
            response = connection.getresponse()
            raw = response.read(1048576)
            if response.status != expected:
                raise AssertionError("Integration HTTP status differs from the contract.")
            return json.loads(raw), dict(response.getheaders())
        finally:
            connection.close()

    def stop(self, *, graceful=False):
        if self.process is not None and self.process.poll() is None:
            try:
                if graceful:
                    self.process.send_signal(
                        signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
                    )
                else:
                    self.process.terminate()
                self.process.wait(timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=10)
                if graceful:
                    raise AssertionError("Fixture service did not shut down gracefully.") from None
            finally:
                if self.log:
                    self.log.close()
        elif self.log:
            self.log.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()
