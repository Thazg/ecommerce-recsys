"""Enforce hosted-only demo, documentation and secret-scanning gates."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
from scripts.check_release_workflows import ACTIONS, PYTHON_VERSION, read  # noqa: E402

WORKFLOW = ".github/workflows/publication.yml"
NODE_VERSION = "24.16.0"
NODE_ACTION = "249970729cb0ef3589644e2896645e5dc5ba9c38"
SCANNER_VERSION = "8.30.1"
SCANNER_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
NODE_TESTS = "node --test --test-isolation=none tests/web/test_snapshot_demo.mjs tests/web/test_shopping_demo.mjs"
DOC_CHECK = "python -I -S scripts/verify_project_documentation.py --check benchmarks/release/project_documentation_publication_validation_v1.json"
INSTALL = f'''curl --fail --silent --show-error --location --connect-timeout 15 --max-time 120 --output "$RUNNER_TEMP/gitleaks.tar.gz" https://github.com/gitleaks/gitleaks/releases/download/v{SCANNER_VERSION}/gitleaks_{SCANNER_VERSION}_linux_x64.tar.gz
echo "{SCANNER_SHA256}  $RUNNER_TEMP/gitleaks.tar.gz" | sha256sum --check --status
tar -xzf "$RUNNER_TEMP/gitleaks.tar.gz" -C "$RUNNER_TEMP" gitleaks
mkdir -p .local
: > .local/secret-scan-ignore'''
SCAN_FLAGS = "--config .gitleaks.toml --gitleaks-ignore-path .local/secret-scan-ignore --ignore-gitleaks-allow --redact=100 --no-banner --no-color --timeout=120 ."
SCAN_HISTORY = f'"$RUNNER_TEMP/gitleaks" git --log-opts=--all {SCAN_FLAGS}'
SCAN_TREE = f'"$RUNNER_TEMP/gitleaks" dir {SCAN_FLAGS}'
PROVENANCE_PATH = r"(?:^|[\\/])benchmarks[\\/](?:(?:release|serving)[\\/][^\\/]+|deployment[\\/](?:local_demonstration_validation_v1|local_release(?:_boundary|_maintenance)?_validation_v1))\.json$"
PROVENANCE_LINE = r'^\s*"(?:docs/(?:API_HARDENING|RECOMMENDATION_API)\.md|scripts/verify_recommendation_api\.py|tests/unit/test_(?:api_hardening|api_verification|recommendation_api)\.py|openapi_sha256)"\s*:\s*"[0-9a-f]{64}",?\s*$'


def validate(data):
    if (
        not isinstance(data, dict)
        or set(data) != {"name", "on", "permissions", "concurrency", "jobs"}
        or data["permissions"] != {"contents": "read"}
        or data["on"] != {"push": {"branches": ["main"]}, "pull_request": {"branches": ["main"]}}
        or not isinstance(data["concurrency"], dict)
        or data["concurrency"]
        != {
            "group": "publication-${{ github.workflow }}-${{ github.ref }}",
            "cancel-in-progress": True,
        }
        or data["concurrency"].get("cancel-in-progress") is not True
        or not isinstance(data["jobs"], dict)
        or set(data["jobs"]) != {"public"}
    ):
        raise ValueError("Publication checks require read-only hosted PR/main execution.")
    job = data["jobs"]["public"]
    if (
        not isinstance(job, dict)
        or set(job) != {"name", "runs-on", "timeout-minutes", "steps"}
        or job["runs-on"] != "ubuntu-24.04"
        or type(job["timeout-minutes"]) is not int
        or job["timeout-minutes"] != 15
        or not isinstance(job["steps"], list)
        or len(job["steps"]) != 8
    ):
        raise ValueError("Publication jobs cannot use private runners or weakened gates.")
    action_settings = [
        (
            "actions/checkout",
            ACTIONS["actions/checkout"],
            {"ref": "${{ github.sha }}", "persist-credentials": False, "fetch-depth": 0},
        ),
        (
            "actions/setup-python",
            ACTIONS["actions/setup-python"],
            {"python-version": PYTHON_VERSION},
        ),
        (
            "actions/setup-node",
            NODE_ACTION,
            {"node-version": NODE_VERSION, "package-manager-cache": False},
        ),
    ]
    for step, (action, pin, settings) in zip(job["steps"][:3], action_settings, strict=True):
        if (
            not isinstance(step, dict)
            or set(step) != {"name", "uses", "with"}
            or step["uses"] != f"{action}@{pin}"
            or step["with"] != settings
            or (
                action == "actions/checkout"
                and (
                    step["with"]["persist-credentials"] is not False
                    or type(step["with"]["fetch-depth"]) is not int
                )
            )
            or (
                action == "actions/setup-node"
                and step["with"]["package-manager-cache"] is not False
            )
        ):
            raise ValueError("Publication actions require exact immutable identities/settings.")
    commands = [INSTALL, SCAN_HISTORY, SCAN_TREE, NODE_TESTS, DOC_CHECK]
    for step, command in zip(job["steps"][3:], commands, strict=True):
        if (
            not isinstance(step, dict)
            or set(step) != {"name", "run"}
            or not isinstance(step["run"], str)
            or step["run"].strip() != command
        ):
            raise ValueError("Publication gates cannot skip, suppress findings or alter scope.")
    return {"node": NODE_VERSION, "gitleaks": SCANNER_VERSION, "required_gates": 5}


def validate_scanner(config):
    expected = {
        "title": "Recommendation project secret scanning",
        "extend": {"useDefault": True},
        "allowlists": [
            {
                "description": "SHA-256 entries for verified API source and OpenAPI provenance",
                "targetRules": ["generic-api-key"],
                "condition": "AND",
                "regexTarget": "line",
                "paths": [PROVENANCE_PATH],
                "regexes": [PROVENANCE_LINE],
            }
        ],
    }
    if config != expected or config.get("extend", {}).get("useDefault") is not True:
        raise ValueError(
            "Scanner exceptions must be limited to reviewed provenance SHA-256 entries."
        )


def check(root=ROOT):
    result = validate(read(root / WORKFLOW))
    config = root / ".gitleaks.toml"
    if config.is_symlink() or not config.is_file() or config.stat().st_size > 16 * 1024:
        raise ValueError("Scanner configuration must be a bounded regular file.")
    validate_scanner(tomllib.loads(config.read_text(encoding="utf-8")))
    source = read(root / ".github/workflows/ci.yml")
    commands = [step.get("run", "") for step in source["jobs"]["test"]["steps"]]
    if "python scripts/check_public_workflow.py" not in commands or not any(
        "actionlint" in command and WORKFLOW in command for command in commands
    ):
        raise ValueError("Hosted Python CI must enforce and lint the publication workflow.")
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(check()))
    except (ValueError, OSError) as error:
        raise SystemExit(f"Publication workflow verification failed: {error}") from error
