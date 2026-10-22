"""Static deployment must not expose the repository, model state or private files."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = {
    "demo/index.html",
    "demo/styles.css",
    "demo/app.js",
    "demo/schema.mjs",
    "demo/transport.mjs",
    "demo/favicon.svg",
    "demo/data/showcase_v1.json",
}


def test_static_output_and_manual_deployment_scope():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert set(config) == {
        "$schema",
        "framework",
        "buildCommand",
        "installCommand",
        "outputDirectory",
        "git",
        "headers",
    }
    assert config["framework"] is None
    assert config["buildCommand"] == config["installCommand"] == ""
    assert config["outputDirectory"] == "demo"
    assert config["git"] == {"deploymentEnabled": False}
    assert config["git"]["deploymentEnabled"] is False


def test_same_origin_security_headers_apply_to_all_static_paths():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert len(config["headers"]) == 1
    rule = config["headers"][0]
    assert set(rule) == {"source", "headers"} and rule["source"] == "/(.*)"
    headers = {entry["key"].lower(): entry["value"] for entry in rule["headers"]}
    assert len(headers) == len(rule["headers"]) == 6
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert headers["cache-control"] == "public, max-age=0, must-revalidate"
    directives = {}
    for directive in headers["content-security-policy"].split(";"):
        name, *values = directive.split()
        assert name not in directives
        directives[name] = values
    for name in ("default-src", "base-uri", "form-action", "frame-ancestors"):
        assert directives[name] == ["'none'"]
    for name in ("script-src", "style-src", "connect-src", "img-src"):
        assert directives[name] == ["'self'"]


@pytest.fixture
def upload_root(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text(
        (ROOT / ".vercelignore").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def ignored(root, paths):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.excludesFile=",
            "-C",
            str(root),
            "check-ignore",
            "--no-index",
            "-z",
            "--stdin",
        ],
        input=("\0".join(sorted(paths)) + "\0").encode("utf-8"),
        capture_output=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.decode("utf-8").split("\0")[:-1])


def test_only_exact_demo_files_and_config_are_allowed_for_cli_upload(upload_root):
    allowed = PUBLIC_FILES | {"vercel.json"}
    canaries = {
        "AGENTS.md",
        ".local/plan.md",
        ".local/demo-fixed-unit.xml",
        ".git/config",
        ".vercel/project.json",
        ".env",
        ".env.production",
        "data/raw/events.csv",
        "artifacts/retailrocket-fold09-v1/user_factors.npy",
        "src/ecommerce_recsys/service/app.py",
        "scripts/export_snapshot_demo.py",
        "docs/PROJECT_STATUS.md",
        "README.md",
        "pyproject.toml",
        "demo/.env",
        "demo/private.json",
        "demo/private/secret.json",
        "demo/data/full_history.json",
        "demo/data/snapshot.parquet",
        "demo/data/extra/file.txt",
        "demo/index.html.bak",
        "demo/app.js.map",
        "demo/data/showcase_v1.json.bak",
        "private/demo/index.html",
        "demo/nested/vercel.json",
        "demo/vercel.json",
    }
    for name in allowed | canaries:
        path = upload_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("canary", encoding="utf-8")
    assert ignored(upload_root, allowed | canaries) == canaries


@pytest.mark.parametrize("name", ["demo/future.txt", "demo/data/new.json", "future/subdir/file.js"])
def test_new_unreviewed_assets_stay_denied(upload_root, name):
    assert ignored(upload_root, {name}) == {name}


def test_local_vercel_link_metadata_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", ".vercel/project.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ".vercel/project.json"


def test_current_demo_inventory_and_provenance_are_verified():
    from scripts.verify_snapshot_demo import verify

    assert verify(ROOT, ROOT / "benchmarks/demo/showcase_presentation_validation_v1.json")[
        "identity_verified"
    ]
    actual = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "demo").rglob("*") if path.is_file()
    }
    assert actual == PUBLIC_FILES
