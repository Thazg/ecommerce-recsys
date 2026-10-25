"""Publication gates retain complete history, default detectors and hosted isolation."""

import copy
import tomllib

import pytest

from scripts import check_public_workflow as policy


def test_checked_in_publication_policy():
    assert policy.check() == {"node": "24.16.0", "gitleaks": "8.30.1", "required_gates": 5}


@pytest.mark.parametrize(
    "change",
    [
        "event",
        "permissions",
        "runner",
        "deadline",
        "job_skip",
        "job_env",
        "action_pin",
        "shallow",
        "persist",
        "cache",
        "step_skip",
        "soft_fail",
        "no_history",
        "no_tree",
        "no_node",
        "no_docs",
        "no_redaction",
        "allow_comments",
        "wrong_checksum",
        "nonstring_run",
        "extra_step",
    ],
)
def test_publication_policy_rejects_weakened_gates(change):
    data = policy.read(policy.ROOT / policy.WORKFLOW)
    job = data["jobs"]["public"]
    if change == "event":
        data["on"] = {"pull_request_target": {}}
    elif change == "permissions":
        data["permissions"] = {"contents": "write"}
    elif change == "runner":
        job["runs-on"] = ["self-hosted"]
    elif change == "deadline":
        job["timeout-minutes"] = True
    elif change == "job_skip":
        job["if"] = "false"
    elif change == "job_env":
        job["env"] = {"GITLEAKS_CONFIG": "other.toml"}
    elif change == "action_pin":
        job["steps"][2]["uses"] = "actions/setup-node@v6"
    elif change == "shallow":
        job["steps"][0]["with"]["fetch-depth"] = 1
    elif change == "persist":
        job["steps"][0]["with"]["persist-credentials"] = True
    elif change == "cache":
        job["steps"][2]["with"]["package-manager-cache"] = 0
    elif change == "step_skip":
        job["steps"][4]["if"] = "false"
    elif change == "soft_fail":
        job["steps"][4]["continue-on-error"] = True
    elif change.startswith("no_") and change not in {"no_redaction"}:
        index = {"no_history": 4, "no_tree": 5, "no_node": 6, "no_docs": 7}[change]
        job["steps"][index]["run"] = "echo skipped"
    elif change == "no_redaction":
        job["steps"][4]["run"] = job["steps"][4]["run"].replace("--redact=100", "")
    elif change == "allow_comments":
        job["steps"][4]["run"] = job["steps"][4]["run"].replace("--ignore-gitleaks-allow", "")
    elif change == "wrong_checksum":
        job["steps"][3]["run"] = job["steps"][3]["run"].replace(policy.SCANNER_SHA256, "0" * 64)
    elif change == "nonstring_run":
        job["steps"][7]["run"] = None
    else:
        job["steps"].append({"name": "other", "run": "echo ignored"})
    with pytest.raises(ValueError):
        policy.validate(data)


@pytest.mark.parametrize(
    "change", ["default", "condition", "rules", "paths", "regex", "extra_allowlist"]
)
def test_scanner_config_cannot_hide_arbitrary_keys_or_whole_directories(change):
    config = tomllib.loads((policy.ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    if change == "default":
        config["extend"]["useDefault"] = 1
    elif change == "condition":
        config["allowlists"][0]["condition"] = "OR"
    elif change == "rules":
        config["allowlists"][0]["targetRules"] = ["github-pat"]
    elif change == "paths":
        config["allowlists"][0]["paths"] = ["benchmarks/"]
    elif change == "regex":
        config["allowlists"][0]["regexes"] = ["[a-f0-9]{64}"]
    else:
        config["allowlists"].append(copy.deepcopy(config["allowlists"][0]))
    with pytest.raises(ValueError):
        policy.validate_scanner(config)
