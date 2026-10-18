"""Explicit integration profiles without changing frozen project metadata."""

import re
from pathlib import Path

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("snapshot integration")
    group.addoption(
        "--run-real-bundle", action="store_true", help="Run explicitly pinned Retailrocket checks."
    )
    group.addoption("--bundle-path", type=Path)
    group.addoption("--bundle-manifest-sha256")
    group.addoption("--bundle-quality-receipt", type=Path)
    group.addoption("--bundle-quality-sha256")
    group.addoption("--bundle-loader-evidence", type=Path)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: fitted snapshot across an actual process/HTTP boundary"
    )
    config.addinivalue_line(
        "markers", "real_bundle: requires explicit external bundle and trusted pins"
    )
    enabled = config.getoption("--run-real-bundle")
    path, pin = config.getoption("--bundle-path"), config.getoption("--bundle-manifest-sha256")
    quality, quality_pin = (
        config.getoption("--bundle-quality-receipt"),
        config.getoption("--bundle-quality-sha256"),
    )
    evidence = config.getoption("--bundle-loader-evidence")
    if not enabled and any(
        value is not None for value in (path, pin, quality, quality_pin, evidence)
    ):
        raise pytest.UsageError("Bundle options require --run-real-bundle.")
    if enabled:
        if evidence is not None and (evidence.exists() or evidence.is_symlink()):
            raise pytest.UsageError(
                "Preserve existing loader evidence; choose a fresh output path."
            )
        if path is None or not path.is_dir() or not re.fullmatch("[0-9a-f]{64}", pin or ""):
            raise pytest.UsageError(
                "Real-bundle checks require an existing bundle and a trusted lowercase SHA-256 pin."
            )
        if (quality is None) != (quality_pin is None) or (
            quality_pin is not None and not re.fullmatch("[0-9a-f]{64}", quality_pin)
        ):
            raise pytest.UsageError("Provide both quality receipt and trusted SHA-256, or neither.")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" in Path(item.path).relative_to(config.rootpath).parts:
            item.add_marker(pytest.mark.integration)
        if item.get_closest_marker("real_bundle") and not config.getoption("--run-real-bundle"):
            item.add_marker(
                pytest.mark.skip(
                    reason="Real bundle not requested; use --run-real-bundle and trusted pins."
                )
            )


def pytest_collection_finish(session):
    if session.config.getoption("--run-real-bundle") and not any(
        item.get_closest_marker("real_bundle") for item in session.items
    ):
        raise pytest.UsageError("--run-real-bundle selected no real-bundle tests.")
