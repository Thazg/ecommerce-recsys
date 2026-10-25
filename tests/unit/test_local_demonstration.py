"""The demonstration launcher retains loopback, authentication and owned cleanup."""

import subprocess

import pytest

from scripts import serve_local_snapshot as launcher
from scripts import verify_local_demonstration as verification


@pytest.mark.parametrize("port", [0, 80, 1023, 65536])
def test_privileged_or_invalid_ports_are_rejected(tmp_path, port):
    with pytest.raises(SystemExit) as error:
        launcher.main(
            ["--bundle-path", str(tmp_path), "--manifest-sha256", "a" * 64, "--port", str(port)]
        )
    assert error.value.code == 2


def test_no_wildcard_bind_argument_is_supported(tmp_path):
    with pytest.raises(SystemExit) as error:
        launcher.main(
            ["--bundle-path", str(tmp_path), "--manifest-sha256", "a" * 64, "--host", "0.0.0.0"]
        )
    assert error.value.code == 2


def test_indexed_launcher_preserves_service_and_security_controls(tmp_path, monkeypatch):
    import uvicorn

    from ecommerce_recsys.artifacts.compact_runtime import load_compact_bundle
    from ecommerce_recsys.serving import observability

    captured = {}
    monkeypatch.delenv("RECSYS_API_TOKEN", raising=False)
    monkeypatch.delenv("RECSYS_API_TOKEN_FILE", raising=False)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(name, "7")
    monkeypatch.setattr(observability, "configure_event_logging", lambda: None)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app, **kwargs))
    launcher.main(["--bundle-path", str(tmp_path), "--manifest-sha256", "a" * 64, "--port", "8766"])
    app = captured.pop("app")
    assert captured["host"] == "127.0.0.1"
    assert captured["workers"] == 1
    assert captured["proxy_headers"] is False
    assert captured["access_log"] is False
    assert captured["lifespan"] == "on"
    assert captured["http"] is not None
    assert app.state.service.loader is load_compact_bundle
    assert app.state.service.bundle is None
    assert app.state.service.settings.cache_max_entries == 0
    assert app.state.service.settings.busy_policy == "reject"
    assert app.state.security.authorities == ("127.0.0.1:8766", "localhost:8766")


@pytest.mark.parametrize("kill_required", [False, True])
def test_owned_stop_reaps_only_the_child(kill_required):
    class Child:
        terminated = killed = False
        waits = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            self.waits += 1
            if kill_required and self.waits == 1:
                raise subprocess.TimeoutExpired("owned", timeout)
            return -1

    child = Child()
    verification.stop_owned(child)
    assert child.terminated
    assert child.killed is kill_required
    assert child.waits == (2 if kill_required else 1)
