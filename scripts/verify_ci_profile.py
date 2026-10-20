"""Reproduce hosted Linux test commands locally using the hashed CPU wheel lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts import check_release_workflows as workflows  # noqa: E402
from scripts import snapshot_release as release  # noqa: E402
from scripts import verify_linux_container as linux  # noqa: E402
from scripts.verify_release import publish  # noqa: E402

COMMANDS = [
    ["python", "-m", "pip", "check"],
    [
        "python",
        "-c",
        "import fastapi, uvicorn, httpx2, yaml, torch, faiss; from fastapi.testclient import TestClient",
    ],
    [
        "actionlint",
        "-shellcheck=",
        "-pyflakes=",
        "-config-file",
        ".github/actionlint.yaml",
        ".github/workflows/ci.yml",
        ".github/workflows/snapshot-release.yml",
    ],
    ["python", "scripts/check_release_workflows.py"],
    ["python", "-m", "ruff", "check", "."],
    ["python", "-m", "ruff", "format", "--check", "."],
    [
        "python",
        "-m",
        "pytest",
        "tests/unit",
        "-q",
        "-o",
        "xfail_strict=true",
        "--junitxml=/reports/unit.xml",
    ],
    [
        "python",
        "-m",
        "pytest",
        "tests/integration",
        "-m",
        "not real_bundle",
        "-q",
        "-o",
        "xfail_strict=true",
        "--junitxml=/reports/fixture.xml",
    ],
    [
        "python",
        "scripts/check_release_workflows.py",
        "--unit-junit",
        "/reports/unit.xml",
        "--fixture-junit",
        "/reports/fixture.xml",
    ],
]


def ci_inputs(root=ROOT):
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
        )
        .decode("utf-8")
        .split("\0")
    )
    roots = {
        "src",
        "scripts",
        "tests",
        "benchmarks",
        "containers",
        "requirements",
        ".github",
    }
    fixed = {
        "README.md",
        "LICENSE",
        "pyproject.toml",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
    }
    extensions = {".py", ".json", ".md", ".toml", ".yml", ".yaml", ".txt", ".lock"}
    selected = []
    for name in sorted(set(names) - {""}):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid public source path.")
        if name not in fixed and not (
            path.parts[0] in roots
            and (path.suffix in extensions or name == "containers/Dockerfile")
        ):
            continue
        # Receipts produced by this gate are not its inputs; excluding them also
        # avoids a self-referential inventory. Documentation is outside test scope.
        if name.startswith(("benchmarks/release/ci_linux", "benchmarks/release/release_workflow")):
            continue
        source = root / path
        if source.is_symlink() or not source.is_file():
            raise ValueError("CI source must contain regular existing files.")
        selected.append(name)
    if not set(release.SOURCE_FILES) <= set(selected):
        raise ValueError("Incomplete CI source inventory.")
    return selected


def hashes(names):
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def actionlint(archive, target):
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 16 * 1024**2:
        raise ValueError("Expected bounded actionlint Linux archive.")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != workflows.ACTIONLINT_SHA256:
        raise ValueError("Actionlint archive checksum differs.")
    with tarfile.open(archive, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name == "actionlint"]
        if len(members) != 1 or not members[0].isfile() or members[0].size > 32 * 1024**2:
            raise ValueError("Expected one regular actionlint executable.")
        with tar.extractfile(members[0]) as handle:
            target.write_bytes(handle.read())


def verify(wheelhouse, archive, output):
    if output.exists() or output.is_symlink():
        raise ValueError("Preserve completed evidence; choose a fresh output.")
    workflows.check()
    source = release.code_identity()
    names = ci_inputs()
    files = hashes(names)
    scratch = linux.scratch_directory()
    context, reports = scratch / "ci-build", scratch / "reports"
    context.mkdir()
    reports.mkdir()
    for name in names:
        target = context / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    actionlint(archive, context / "actionlint")
    base_tag = "recsys-snapshot:qualification"
    base_id = linux.validate_image(linux.inspect("image", base_tag, scratch))
    upstream = workflows.ROOT / "benchmarks/containers/linux_snapshot_boundary_validation_v1.json"
    qualification = release.load_receipt(upstream)
    if (
        qualification.get("qualification_passed") is not True
        or qualification["identity"]["image_id"] != base_id
        or qualification["identity"]["files_sha256"] != linux.sources()
    ):
        raise ValueError("Local CI requires the unchanged qualified serving base.")
    recipe = f"""FROM {base_tag}
USER 0:0
COPY source/requirements/ci-linux.txt /opt/ci/requirements.txt
RUN --mount=type=bind,from=wheels,target=/wheelhouse python -m pip install --no-index --find-links=/wheelhouse --require-hashes --only-binary=:all: -r /opt/ci/requirements.txt
COPY source /workspace
COPY actionlint /usr/local/bin/actionlint
WORKDIR /workspace
RUN python -m pip install --no-deps --no-build-isolation -e . && python -m pip check
RUN chmod 755 /usr/local/bin/actionlint && chown -R 10001:10001 /workspace
ENV PYTHONPATH=/workspace/src:/workspace PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 10001:10001
HEALTHCHECK NONE
ENTRYPOINT ["python"]
CMD ["-c", "import time; time.sleep(1800)"]
"""
    (context / "Dockerfile").write_text(recipe, encoding="utf-8", newline="\n")
    image = "recsys-ci-local:" + uuid.uuid4().hex
    name = "recsys-ci-local-" + uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    owned = False
    try:
        linux.docker(
            [
                "build",
                "--network",
                "none",
                "--build-context",
                f"wheels={wheelhouse.absolute()}",
                "--tag",
                image,
                str(context),
            ],
            scratch,
            timeout=900,
        )
        if linux.validate_image(linux.inspect("image", base_tag, scratch)) != base_id:
            raise ValueError("Serving base changed during CI image build.")
        image_id = linux.inspect("image", image, scratch)["Id"]
        # This is a disposable writable test workspace, never a serving container.
        owned = True
        linux.docker(
            [
                "create",
                "--name",
                name,
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "128",
                "--cpus",
                "2",
                "--memory",
                "4g",
                "--memory-swap",
                "4g",
                "--mount",
                f"type=bind,source={reports.absolute()},target=/reports",
                image_id,
            ],
            scratch,
        )
        linux.docker(["start", name], scratch)
        for command in COMMANDS:
            linux.docker(["exec", name, *command], scratch, timeout=900)
        profiles = workflows.profiles(reports / "unit.xml", reports / "fixture.xml", host="posix")
    finally:
        if owned:
            linux.remove(name, scratch)
    if hashes(names) != files or release.code_identity() != source or ci_inputs() != names:
        raise ValueError("CI source changed while measured.")
    result = {
        "schema_version": 1,
        "verification": "local-linux-ci-profile-v1",
        "functional_passed": True,
        "deployment_eligible": False,
        "github_execution_observed": False,
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "files_lf_sha256": source,
            "ci_inputs_sha256": files,
            "inventory_scope": "ci-build-and-test-inputs-v1",
            "base_image_id": base_id,
            "ci_image_id": image_id,
            "actionlint_archive_sha256": workflows.ACTIONLINT_SHA256,
            "upstream_container_receipt_sha256": release.file_sha(upstream),
        },
        "recipe": recipe,
        "commands": COMMANDS,
        "profiles": profiles,
        "owned_container_cleanup_verified": True,
        "limits": [
            "Docker Desktop Linux/amd64 reproduction, not a GitHub-hosted job or Ubuntu runner attestation.",
            "CPU Torch/Faiss test wheels do not alter the qualified serving image.",
            "No Retailrocket data/model mounts or serving/load qualification.",
            "Inventory covers CI build/test inputs, not documentation or this gate's generated receipts.",
        ],
    }
    publish(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--actionlint-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.wheelhouse, args.actionlint_archive, args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError):
        parser.exit(
            1,
            "Local Linux CI profile failed; no success receipt published. Inspect private Docker logs.\n",
        )
    print(json.dumps({"functional_passed": True, "output": args.output.as_posix()}))


if __name__ == "__main__":
    main()
