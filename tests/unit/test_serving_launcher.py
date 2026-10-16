"""Exercise launcher settings without opening a listener or loading a model."""

# ruff: noqa: E402

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="Install requirements/serving-test.txt for API tests.")
import uvicorn

from ecommerce_recsys.serving import __main__ as launcher
from ecommerce_recsys.serving import app as serving_app


@pytest.fixture
def launch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("RECSYS_BUNDLE_PATH", str(tmp_path / "bundle with spaces"))
    monkeypatch.setenv("RECSYS_MANIFEST_SHA256", "a" * 64)
    monkeypatch.setattr(serving_app, "create_app", lambda settings: settings)
    monkeypatch.setattr(
        uvicorn, "run", lambda settings, **options: calls.append((settings, options))
    )

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["recommendation-api", *args])
        launcher.main()
        return calls

    return invoke


def test_env_only_launcher_converts_path_and_uses_one_loopback_worker(launch):
    settings, options = launch()[0]
    assert isinstance(settings.bundle_path, Path)
    assert settings.bundle_path.name == "bundle with spaces"
    assert settings.manifest_sha256 == "a" * 64
    assert options["host"] == "127.0.0.1"
    assert options["workers"] == 1 and options["access_log"] is False


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_explicit_loopback_and_flags_override_environment(launch, host):
    settings, options = launch(
        "--bundle-path", "explicit", "--manifest-sha256", "b" * 64, "--host", host, "--port", "8081"
    )[0]
    assert settings.bundle_path == Path("explicit") and settings.manifest_sha256 == "b" * 64
    assert options["host"] == ("127.0.0.1" if host == "localhost" else host)
    assert options["port"] == 8081


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "example.com"])
def test_non_loopback_bind_is_rejected(launch, host):
    with pytest.raises(SystemExit) as error:
        launch("--host", host)
    assert error.value.code == 2
