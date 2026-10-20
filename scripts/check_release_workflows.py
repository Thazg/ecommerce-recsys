"""Validate the finite hosted/private workflow policy and explicit JUnit profiles."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
from scripts.release_validation import junit_summary  # noqa: E402

ACTIONS = {
    "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/upload-artifact": "b7c566a772e6b6bfb58ed0dc250532a479d7789f",
}
ACTIONLINT_SHA256 = "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"
PYTHON_VERSION = "3.13.15"
MANIFEST_SHA256 = "84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe"
DEPENDENCY_IMPORT = 'python -c "import fastapi, uvicorn, httpx2, yaml, torch, faiss; from fastapi.testclient import TestClient"'
PRIVATE_IF = "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' && github.event.repository.private == true && github.repository != 'Thazg/ecommerce-recsys' && github.repository_owner == 'Thazg' && inputs.local_qualification_only == true"


class Loader(yaml.SafeLoader):
    pass


Loader.yaml_implicit_resolvers = {
    k: [pair for pair in values if pair[0] != "tag:yaml.org,2002:bool"]
    for k, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF")
)


def unique(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError("Duplicate workflow key.")
        result[key] = loader.construct_object(value_node)
    return result


Loader.add_constructor("tag:yaml.org,2002:map", unique)


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
        raise ValueError("Workflow must be a bounded regular file.")
    text = path.read_text(encoding="utf-8")
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
        raise ValueError("Workflow aliases are not supported.")
    return yaml.load(text, Loader=Loader)


def validate_source_ci(source, main, runs):
    if (
        not isinstance(source, str)
        or not re.fullmatch(r"[0-9a-f]{40}", source)
        or main.get("object", {}).get("sha") != source
    ):
        raise ValueError("Requested source is not current source main.")
    candidates = [
        row
        for row in runs.get("workflow_runs", [])
        if row.get("head_sha") == source
        and row.get("event") == "push"
        and row.get("head_branch") == "main"
        and row.get("path") == ".github/workflows/ci.yml"
        and row.get("repository", {}).get("full_name", "").lower() == "thazg/ecommerce-recsys"
    ]
    if not candidates or any(
        type(row.get(key)) is not int or not 0 < row[key] < 2**63
        for row in candidates
        for key in ("id", "run_number", "run_attempt")
    ):
        raise ValueError("No complete matching source CI run.")
    latest = max(candidates, key=lambda row: (row["run_number"], row["run_attempt"]))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("Latest matching source CI attempt is not successful.")
    return {
        "source_sha": source,
        "run_id": latest["id"],
        "run_number": latest["run_number"],
        "run_attempt": latest["run_attempt"],
        "conclusion": "success",
    }


def source_ci(source):
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Expected an immutable source SHA.")

    token = os.environ.get("SNAPSHOT_SOURCE_TOKEN", "")
    if len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("Invalid source credential format.")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("Source metadata redirects are not accepted.")

    opener = urllib.request.build_opener(NoRedirect)

    def get(path):
        request = urllib.request.Request(
            "https://api.github.com/repos/Thazg/ecommerce-recsys/" + path,
            headers={
                "User-Agent": "snapshot-release-qualification",
                "Accept": "application/vnd.github+json",
            },
        )
        if token:
            request.add_header("Authorization", "Bearer " + token)
        with opener.open(request, timeout=15) as response:
            raw = response.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError("Public CI metadata exceeds its bound.")
        return json.loads(raw)

    main = get("git/ref/heads/main")
    runs = get(
        "actions/workflows/ci.yml/runs?"
        + urllib.parse.urlencode({"head_sha": source, "event": "push", "per_page": 100})
    )
    return validate_source_ci(source, main, runs)


def validate(data, *, private=False):
    if (
        not isinstance(data, dict)
        or set(data) != {"name", "on", "permissions", "concurrency", "jobs"}
        or data["permissions"] != {"contents": "read"}
        or set(data["jobs"]) != ({"qualify"} if private else {"test"})
    ):
        raise ValueError("Workflow topology or minimal permissions differ.")
    job = data["jobs"]["qualify" if private else "test"]
    allowed_job = {"name", "runs-on", "timeout-minutes", "env", "steps"} | (
        {"if", "environment"} if private else set()
    )
    if (
        set(job) - allowed_job
        or "permissions" in job
        or type(job.get("timeout-minutes")) is not int
        or job["timeout-minutes"] != (60 if private else 20)
    ):
        raise ValueError("Job permissions/deadline differ.")
    if private:
        if (
            set(data["on"]) != {"workflow_call"}
            or job.get("if") != PRIVATE_IF
            or job.get("runs-on") != ["self-hosted", "Windows", "X64", "snapshot-qualification"]
            or job.get("environment") != "snapshot-qualification"
            or data["concurrency"]
            != {"group": "snapshot-qualification", "cancel-in-progress": False}
            or job.get("env", {}).get("SNAPSHOT_WORK_ROOT") != "${{ vars.SNAPSHOT_WORK_ROOT }}"
            or job.get("env", {}).get("SNAPSHOT_MANIFEST_SHA256") != MANIFEST_SHA256
            or job.get("env", {}).get("PYTHONPATH")
            != "${{ github.workspace }}/src;${{ github.workspace }}"
        ):
            raise ValueError(
                "Real qualification requires a private manual caller and protected environment."
            )
        if data["on"]["workflow_call"].get("secrets") != {
            "source_read_token": {
                "description": "Read-only source contents and Actions metadata",
                "required": True,
            }
        } or "SNAPSHOT_SOURCE_TOKEN" in job.get("env", {}):
            raise ValueError("Private source checkout requires an explicit read-only credential.")
        credential_steps = [
            step for step in job["steps"] if "SNAPSHOT_SOURCE_TOKEN" in step.get("env", {})
        ]
        if [step.get("name") for step in credential_steps] != [
            "Require a reviewed current source revision before checkout",
            "Verify workflow policy",
        ] or any(
            step["env"]["SNAPSHOT_SOURCE_TOKEN"] != "${{ secrets.source_read_token }}"
            for step in credential_steps
        ):
            raise ValueError("Source credential must be scoped to metadata checks only.")
        inputs = data["on"]["workflow_call"]["inputs"]
        if (
            set(inputs) != {"source_sha", "local_qualification_only"}
            or inputs["source_sha"].get("type") != "string"
            or inputs["source_sha"].get("required") is not True
            or inputs["local_qualification_only"].get("type") != "boolean"
            or inputs["local_qualification_only"].get("required") is not True
            or "default" in inputs["local_qualification_only"]
        ):
            raise ValueError("Private qualification inputs differ.")
    elif (
        data["on"] != {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}}
        or job.get("runs-on") != "ubuntu-24.04"
        or "environment" in job
        or "if" in job
        or data["concurrency"]
        != {"group": "ci-${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": True}
    ):
        raise ValueError("Pull-request jobs must use the hosted test profile only.")
    seen, commands = [], []
    for step in job["steps"]:
        if not isinstance(step, dict) or "uses" in step and "run" in step:
            raise ValueError("Invalid workflow step.")
        allowed_step = (
            {"name", "uses", "with", "if"} if "uses" in step else {"name", "run", "shell", "env"}
        )
        if set(step) - allowed_step:
            raise ValueError(
                "Workflow steps cannot soften failure handling or inject extra behavior."
            )
        if "uses" in step:
            repo, sep, pin = step["uses"].partition("@")
            if not sep or ACTIONS.get(repo) != pin:
                raise ValueError("Actions require verified immutable commit pins.")
            if "if" in step and not (
                repo == "actions/upload-artifact" and not private and step["if"] == "always()"
            ):
                raise ValueError("Required actions cannot be conditionally skipped.")
            seen.append(repo)
            settings = step.get("with", {})
            if repo == "actions/checkout":
                if (
                    settings.get("persist-credentials") is not False
                    or settings.get("fetch-depth") != 0
                    or settings.get("ref")
                    != ("${{ inputs.source_sha }}" if private else "${{ github.sha }}")
                    or (private and settings.get("repository") != "Thazg/ecommerce-recsys")
                    or (private and settings.get("token") != "${{ secrets.source_read_token }}")
                ):
                    raise ValueError("Checkout identity or credential persistence differs.")
            elif repo == "actions/setup-python":
                if settings != {"python-version": PYTHON_VERSION}:
                    raise ValueError("Hosted CI requires the exact qualified Python version.")
            elif repo == "actions/upload-artifact":
                expected = (
                    {
                        "${{ env.SNAPSHOT_RUN_ROOT }}/linux-qualification.json",
                        "${{ env.SNAPSHOT_RUN_ROOT }}/release-workflow.json",
                        "${{ env.SNAPSHOT_RUN_ROOT }}/unit.xml",
                        "${{ env.SNAPSHOT_RUN_ROOT }}/fixture.xml",
                    }
                    if private
                    else {".local/ci/*.xml"}
                )
                if (
                    set(settings.get("path", "").splitlines()) != expected
                    or settings.get("if-no-files-found") != "error"
                    or settings.get("retention-days") != 7
                    or settings.get("include-hidden-files") is not True
                ):
                    raise ValueError("Only bounded selected reports may upload.")
        elif "run" in step:
            command = step["run"]
            if not isinstance(command, str) or "${{" in command or "if" in step:
                raise ValueError(
                    "Run steps cannot interpolate event expressions or silently skip gates."
                )
            commands.append(command)
        else:
            raise ValueError("Step must run a command or a pinned action.")
    if seen != (
        ["actions/checkout", "actions/upload-artifact"]
        if private
        else ["actions/checkout", "actions/setup-python", "actions/upload-artifact"]
    ):
        raise ValueError("Required pinned action sequence differs.")
    text = "\n".join(commands)
    if private:
        if (
            "https://api.github.com/repos/Thazg/ecommerce-recsys/git/ref/heads/main"
            not in commands[0]
            or "^[0-9a-f]{40}$" not in commands[0]
            or "scripts/verify_linux_container.py" not in text
            or "scripts/verify_release_workflow.py" not in text
            or "--qualification-sha256 $qualificationPin" not in text
            or "--require-source-ci $env:SNAPSHOT_SOURCE_SHA" not in text
            or "-m pytest tests/unit" not in text
            or "-m pytest tests/integration" not in text
            or '--unit-junit "$env:SNAPSHOT_RUN_ROOT/unit.xml" --fixture-junit "$env:SNAPSHOT_RUN_ROOT/fixture.xml"'
            not in text
            or "--work-root $env:SNAPSHOT_RUN_ROOT" not in text
            or "require_idle_work_root" not in text
            or "IsPathFullyQualified($env:SNAPSHOT_WORK_ROOT)" not in commands[0]
            or "Recovery storage must be outside checkout" not in commands[0]
            or "Recovery storage resolves inside checkout" not in commands[0]
            or "SNAPSHOT_RUN_ROOT=$runRoot" not in commands[0]
            or "b.is_dir() and not b.is_relative_to(w)" not in commands[0]
            or "not e.is_relative_to(w)" not in commands[0]
            or "IsPathFullyQualified($env:SNAPSHOT_BUNDLE)" not in commands[0]
            or "sys.version_info[:3] == (3,13,15)" not in text
        ):
            raise ValueError("Missing real bundle, source or lifecycle gates.")
    else:
        required = [
            "python -m pip install --require-hashes --only-binary=:all: -r requirements/ci-linux.txt",
            "python -m pip install --no-deps --no-build-isolation -e .",
            "python -m pip check",
            DEPENDENCY_IMPORT,
            "python scripts/check_release_workflows.py",
            "python -m ruff check .",
            "python -m ruff format --check .",
            "python -m pytest tests/unit -q -o xfail_strict=true --junitxml=.local/ci/unit.xml",
            'python -m pytest tests/integration -m "not real_bundle" -q -o xfail_strict=true --junitxml=.local/ci/fixture.xml',
            "python scripts/check_release_workflows.py --unit-junit .local/ci/unit.xml --fixture-junit .local/ci/fixture.xml",
        ]
        if any(command not in commands for command in required):
            raise ValueError("Missing or weakened hosted CI gate.")
        if not any(
            "https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_linux_amd64.tar.gz"
            in command
            and ACTIONLINT_SHA256 in command
            and "sha256sum --check --status" in command
            and "-config-file .github/actionlint.yaml" in command
            for command in commands
        ):
            raise ValueError("Workflow schema lint must verify the pinned binary checksum.")
    return {"private_caller_only": private, "actions_pinned": len(seen), "run_steps": len(commands)}


def check(root=ROOT):
    lock = root / "requirements/ci-linux.txt"
    packages = {}
    cpu_index = "--extra-index-url https://download.pytorch.org/whl/cpu"
    directives = 0
    for line in lock.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        if line == cpu_index:
            directives += 1
            continue
        match = re.fullmatch(r"([a-z0-9-]+)==([a-zA-Z0-9.+]+) --hash=sha256:([a-f0-9]{64})", line)
        if not match or match[1] in packages:
            raise ValueError("CI requires unique exact hashed binary requirements.")
        packages[match[1]] = match[2]
    if (
        directives != 1
        or packages.get("torch") != "2.14.1+cpu"
        or packages.get("faiss-cpu") != "1.15.1"
    ):
        raise ValueError("Optional model tests require pinned CPU Torch/Faiss, not silent skips.")
    lines = set(lock.read_text().splitlines())
    for relative in ("containers/runtime.lock", "containers/build.lock"):
        required = {
            s for s in (root / relative).read_text().splitlines() if s and not s.startswith("#")
        }
        if not required <= lines:
            raise ValueError("CI must retain the frozen runtime and build wheel hashes.")
    return {
        "hosted": validate(read(root / ".github/workflows/ci.yml")),
        "real_qualification": validate(
            read(root / ".github/workflows/snapshot-release.yml"), private=True
        ),
    }


def profiles(unit, fixture, *, host=os.name):
    result = {
        "unit": junit_summary(unit, profile="unit", host=host),
        "fixture": junit_summary(fixture, profile="fixture", host=host),
    }
    if any(reason != "windows_symlink_privilege" for reason in result["unit"]["skip_reasons"]):
        raise ValueError("Release CI cannot omit optional model coverage.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit-junit", type=Path)
    parser.add_argument("--fixture-junit", type=Path)
    parser.add_argument("--require-source-ci")
    args = parser.parse_args()
    if (args.unit_junit is None) != (args.fixture_junit is None):
        parser.error("Provide both explicit JUnit profiles together.")
    try:
        result = {"workflow_policy": check()}
        if args.require_source_ci:
            result["source_ci"] = source_ci(args.require_source_ci)
        if args.unit_junit:
            result["profiles"] = profiles(args.unit_junit, args.fixture_junit)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
        parser.exit(1, "Workflow/profile policy verification failed.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
