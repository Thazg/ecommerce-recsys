"""Workflow policy rejects unsafe runners, mutable actions and weakened gates."""

import copy
import io
import json

import pytest
import yaml

from scripts import check_release_workflows as policy


def test_checked_in_workflow_policies():
    result = policy.check()
    assert result["hosted"]["actions_pinned"] == 3
    assert result["real_qualification"]["private_caller_only"] is True


@pytest.mark.parametrize(
    "change",
    ["event", "permissions", "runner", "pin", "skip", "remove_gate", "credentials", "upload"],
)
def test_hosted_workflow_rejects_weakened_boundary(change):
    data = policy.read(policy.ROOT / ".github/workflows/ci.yml")
    job = data["jobs"]["test"]
    if change == "event":
        data["on"] = {"pull_request_target": {}}
    elif change == "permissions":
        data["permissions"] = {"contents": "write"}
    elif change == "runner":
        job["runs-on"] = ["self-hosted"]
    elif change == "pin":
        job["steps"][0]["uses"] = "actions/checkout@v5"
    elif change == "skip":
        job["steps"][7]["if"] = "false"
    elif change == "remove_gate":
        job["steps"] = [s for s in job["steps"] if s.get("run") != "python -m pip check"]
    elif change == "credentials":
        job["steps"][0]["with"]["persist-credentials"] = True
    else:
        job["steps"][-1]["with"]["path"] = ".local/**"
    with pytest.raises(ValueError):
        policy.validate(data)


@pytest.mark.parametrize(
    "change",
    ["public", "automatic", "cancel", "unprotected", "mutable_ref", "interpolation", "upload"],
)
def test_real_lane_requires_private_manual_owner_context(change):
    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    job = data["jobs"]["qualify"]
    if change == "public":
        job["if"] = "true"
    elif change == "automatic":
        data["on"]["push"] = {}
    elif change == "cancel":
        data["concurrency"]["cancel-in-progress"] = True
    elif change == "unprotected":
        job.pop("environment")
    elif change == "mutable_ref":
        job["steps"][1]["with"]["ref"] = "main"
    elif change == "interpolation":
        job["steps"][0]["run"] += "\necho ${{ inputs.source_sha }}"
    else:
        job["steps"][-1]["with"]["path"] = "artifacts/**"
    with pytest.raises(ValueError):
        policy.validate(data, private=True)


@pytest.mark.parametrize("text", ["a: 1\na: 2\n", "a: &shared {}\nb: *shared\n"])
def test_yaml_rejects_duplicate_keys_and_aliases(tmp_path, text):
    path = tmp_path / "workflow.yml"
    path.write_text(text)
    with pytest.raises((ValueError, yaml.YAMLError)):
        policy.read(path)


def test_yaml_on_key_and_boolean_types_remain_distinct(tmp_path):
    path = tmp_path / "workflow.yml"
    path.write_text("on:\n  workflow_call: {}\nflag: false\n")
    data = policy.read(path)
    assert "on" in data and True not in data and data["flag"] is False


def test_unknown_extra_job_cannot_bypass_hosted_profile():
    data = policy.read(policy.ROOT / ".github/workflows/ci.yml")
    data["jobs"]["extra"] = copy.deepcopy(data["jobs"]["test"])
    with pytest.raises(ValueError):
        policy.validate(data)


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "failed",
        "foreign_sha",
        "foreign_branch",
        "wrong_path",
        "bad_counter",
        "newer_failed",
    ],
)
def test_release_requires_latest_successful_ci_for_exact_source_main(change):
    source = "a" * 40
    main = {"object": {"sha": source}}
    row = {
        "id": 1,
        "run_number": 1,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "head_sha": source,
        "event": "push",
        "head_branch": "main",
        "path": ".github/workflows/ci.yml",
        "repository": {"full_name": "Thazg/ecommerce-recsys"},
    }
    assert policy.validate_source_ci(source, main, {"workflow_runs": [row]})["run_id"] == 1
    runs = [row]
    if change == "pending":
        row["status"] = "in_progress"
    elif change == "failed":
        row["conclusion"] = "failure"
    elif change == "foreign_sha":
        main["object"]["sha"] = "b" * 40
    elif change == "foreign_branch":
        row["head_branch"] = "feature"
    elif change == "wrong_path":
        row["path"] = "other.yml"
    elif change == "bad_counter":
        row["run_attempt"] = True
    else:
        runs.append({**row, "run_attempt": 2, "conclusion": "failure"})
    with pytest.raises(ValueError):
        policy.validate_source_ci(source, main, {"workflow_runs": runs})


def test_private_source_token_is_header_only_and_not_returned(monkeypatch):
    source = "a" * 40
    calls = []
    bodies = [
        {"object": {"sha": source}},
        {
            "workflow_runs": [
                {
                    "id": 1,
                    "run_number": 2,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": source,
                    "event": "push",
                    "head_branch": "main",
                    "path": ".github/workflows/ci.yml",
                    "repository": {"full_name": "Thazg/ecommerce-recsys"},
                }
            ]
        },
    ]

    class Opener:
        def open(self, request, timeout):
            assert timeout == 15
            calls.append(request)
            return io.BytesIO(json.dumps(bodies.pop(0)).encode())

    monkeypatch.setenv("SNAPSHOT_SOURCE_TOKEN", "test-read-only-value")
    monkeypatch.setattr(policy.urllib.request, "build_opener", lambda *a: Opener())
    result = policy.source_ci(source)
    assert len(calls) == 2
    assert all(r.get_header("Authorization") == "Bearer test-read-only-value" for r in calls)
    assert all("test-read-only-value" not in r.full_url for r in calls)
    assert "test-read-only-value" not in json.dumps(result)


def test_private_source_credential_cannot_be_implicitly_removed():
    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    data["on"]["workflow_call"].pop("secrets")
    with pytest.raises(ValueError):
        policy.validate(data, private=True)


def test_current_profiles_reject_optional_model_skips(monkeypatch):
    def summary(path, *, profile, host):
        return {"skip_reasons": ["optional_experiment_dependency"] if profile == "unit" else []}

    monkeypatch.setattr(policy, "junit_summary", summary)
    with pytest.raises(ValueError, match="optional model"):
        policy.profiles("unit", "fixture", host="posix")


def test_source_secret_is_not_available_to_model_or_test_steps():
    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    data["jobs"]["qualify"]["env"]["SNAPSHOT_SOURCE_TOKEN"] = "${{ secrets.source_read_token }}"
    with pytest.raises(ValueError):
        policy.validate(data, private=True)


@pytest.mark.parametrize("change", ["job_continue", "step_continue", "skip_checkout"])
def test_required_gates_cannot_turn_failures_into_success(change):
    data = policy.read(policy.ROOT / ".github/workflows/ci.yml")
    job = data["jobs"]["test"]
    if change == "job_continue":
        job["continue-on-error"] = True
    elif change == "step_continue":
        job["steps"][3]["continue-on-error"] = True
    else:
        job["steps"][0]["if"] = "false"
    with pytest.raises(ValueError):
        policy.validate(data)


@pytest.mark.parametrize("change", ["root", "precheckout_guard", "argument"])
def test_real_lane_cannot_put_recovery_storage_back_in_checkout(change):
    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    job = data["jobs"]["qualify"]
    if change == "root":
        job["env"]["SNAPSHOT_WORK_ROOT"] = "${{ github.workspace }}/.local"
    elif change == "precheckout_guard":
        job["steps"][0]["run"] = job["steps"][0]["run"].replace(
            "Recovery storage must be outside checkout", "ignore"
        )
    else:
        for step in job["steps"]:
            if "run" in step:
                step["run"] = step["run"].replace("--work-root $env:SNAPSHOT_RUN_ROOT", "")
    with pytest.raises(ValueError):
        policy.validate(data, private=True)


@pytest.mark.parametrize("change", ["python", "missing_imports", "weakened_imports", "manifest"])
def test_qualified_runtime_and_model_identity_are_required(change):
    private = change == "manifest"
    data = policy.read(
        policy.ROOT / ".github/workflows" / ("snapshot-release.yml" if private else "ci.yml")
    )
    job = data["jobs"]["qualify" if private else "test"]
    if change == "python":
        next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/setup-python@")
        )["with"]["python-version"] = "3.13"
    elif change == "manifest":
        job["env"]["SNAPSHOT_MANIFEST_SHA256"] = "0" * 64
    elif change == "missing_imports":
        job["steps"] = [
            step for step in job["steps"] if step.get("run") != policy.DEPENDENCY_IMPORT
        ]
    else:
        next(step for step in job["steps"] if step.get("run") == policy.DEPENDENCY_IMPORT)[
            "run"
        ] = 'python -c "import yaml"'
    with pytest.raises(ValueError):
        policy.validate(data, private=private)


@pytest.mark.parametrize("change", ["bundle", "interpreter", "patch"])
def test_private_lane_protects_inputs_before_checkout(change):
    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    steps = data["jobs"]["qualify"]["steps"]
    if change == "patch":
        steps[2]["run"] = steps[2]["run"].replace(
            "sys.version_info[:3] == (3,13,15)", "sys.version_info[:2] == (3,13)"
        )
    else:
        original = steps[0]["run"]
        weakened = original.replace(
            "b.is_dir() and not b.is_relative_to(w)"
            if change == "bundle"
            else "not e.is_relative_to(w)",
            "True",
        )
        steps[0]["run"] = weakened
    with pytest.raises(ValueError):
        policy.validate(data, private=True)


def test_precheckout_path_guard_uses_physical_ancestry(tmp_path):
    import ast
    import subprocess
    import sys

    data = policy.read(policy.ROOT / ".github/workflows/snapshot-release.yml")
    command = data["jobs"]["qualify"]["steps"][0]["run"]
    line = next(line for line in command.splitlines() if ' -c "from pathlib' in line)
    code = line.split(' -c "', 1)[1].split('" $workRoot', 1)[0]
    ast.parse(code)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    bundle = tmp_path / "checkout-models"
    bundle.mkdir()
    external = tmp_path / "operations"
    valid = subprocess.run(
        [sys.executable, "-c", code, str(external), str(checkout), str(bundle)], capture_output=True
    )
    assert valid.returncode == 0
    inside = checkout / "bundle"
    inside.mkdir()
    invalid = subprocess.run(
        [sys.executable, "-c", code, str(external), str(checkout), str(inside)], capture_output=True
    )
    assert invalid.returncode != 0 and b"Bundle must be outside" in invalid.stderr
    assert inside.exists()
