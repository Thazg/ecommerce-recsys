"""Only public source and checksum-verified tools enter the disposable CI image."""

import subprocess

import pytest

from scripts import verify_ci_profile as ci


def test_ci_context_excludes_private_and_generated_files(tmp_path, monkeypatch):
    names = list(ci.release.SOURCE_FILES) + [
        ".local/secret.json",
        "AGENTS.md",
        ".env",
        "docs/PROJECT_STATUS.md",
        "benchmarks/release/ci_linux_future.json",
        "benchmarks/release/release_workflow_future.json",
        "data/raw/events.csv",
        "artifacts/version/user_factors.npy",
        "src/ecommerce_recsys/example.py",
    ]
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "\0".join(names).encode())
    for name in ci.release.SOURCE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    path = tmp_path / "src/ecommerce_recsys/example.py"
    path.parent.mkdir(parents=True)
    path.write_text("")
    selected = ci.ci_inputs(tmp_path)
    assert selected == sorted([*ci.release.SOURCE_FILES, "src/ecommerce_recsys/example.py"])


@pytest.mark.parametrize("name", ["../secret.py", "/secret.py", "scripts/missing.py"])
def test_ci_context_rejects_invalid_or_missing_source(tmp_path, monkeypatch, name):
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: name.encode())
    with pytest.raises(ValueError):
        ci.ci_inputs(tmp_path)


def test_tool_archive_is_rejected_before_extraction(tmp_path):
    archive = tmp_path / "tool.tar.gz"
    archive.write_bytes(b"untrusted")
    target = tmp_path / "actionlint"
    with pytest.raises(ValueError, match="checksum"):
        ci.actionlint(archive, target)
    assert not target.exists()
