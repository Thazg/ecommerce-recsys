"""Free-first cost decisions must not turn local evidence into cloud approval."""

import copy
import json
from pathlib import Path

import pytest

from scripts import assess_deployment as design


@pytest.fixture
def catalog():
    return design.read_json(design.ROOT / design.CATALOG)


def fixture_evidence():
    manifest, image = "a" * 64, "sha256:" + "b" * 64
    summary = {
        "resources": {"rss_max_bytes": 3 * 1024**3},
        "rejection_fraction": 16 / 600,
        "successes": 600,
    }
    steps = []
    for name in (
        "sustained",
        "burst-recovery",
        "memory-pressure",
        "client-disconnect",
        "inflight-drain",
        "startup-bad-pin",
        "startup-missing",
        "startup-corrupt",
        "release-recovery",
    ):
        steps.append({"step": name, "result": {"phases": [{"summary": copy.deepcopy(summary)}]}})
    identity = {"manifest_sha256": manifest, "image_id": image}
    target = {"targets": {"rss_bytes": 2 * 1024**3}}
    return [
        {
            "complete": True,
            "loaded_quality_matches_policy": True,
            "identity": identity,
            "components": {"weights": {"bytes": 100}},
            "component_bytes": 100,
        },
        {
            "qualification_passed": True,
            "deployment_eligible": False,
            "identity": identity,
            "resource_policy": {"memory_limit_bytes": 4 * 1024**3},
        },
        {"operational_passed": True, "deployment_eligible": False, "identity": identity},
        {
            "assessment_completed": True,
            "deployment_eligible": False,
            "identity": identity,
            "policy": target,
            "cells": [{"summary": copy.deepcopy(summary)} for _ in range(4)],
        },
        {
            "operational_passed": True,
            "deployment_eligible": False,
            "identity": identity,
            "policy": target,
            "steps": steps,
        },
    ]


@pytest.fixture
def design_root(tmp_path, monkeypatch, catalog):
    for name in design.SOURCE:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic assessment source", encoding="utf-8")
    p = tmp_path / design.CATALOG
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(catalog), encoding="utf-8")
    pins = {}
    for (name, _), value in zip(design.INPUTS.items(), fixture_evidence(), strict=True):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        key = "payload_sha256" if name.endswith("fold09_v1.json") else "content_sha256"
        p.write_text(json.dumps({**value, key: design.digest(value)}), encoding="utf-8")
        pins[name] = design.sha(p.read_bytes())
    monkeypatch.setattr(design, "INPUTS", pins)
    return tmp_path


def test_free_first_decision_retains_all_deployment_blockers(catalog):
    facts = design.measured_facts(fixture_evidence())
    result = design.decide(catalog, facts)
    decision = result["decision"]
    assert decision["execution_mode"] == "existing_local_only"
    assert decision["preferred_free_investigation"] == "oracle-a1-free"
    assert decision["approved_cloud_host"] is None
    assert decision["cloud_resource_created"] is decision["budget_waiver"] is False
    assert "serving_rss_exceeds_2gib_charter" in decision["blockers"]
    assert all(row["deployment_eligible"] is False for row in result["options"])
    assert facts["single_container_host_floor_bytes"] == 6 * 1024**3
    assert facts["dual_container_host_floor_bytes"] == 10 * 1024**3
    assert facts["retained_and_staging_component_bytes"] == 400


def test_subscription_is_not_free_and_memory_fit_is_not_qualification(catalog):
    result = design.decide(catalog, design.measured_facts(fixture_evidence()))
    options = {row["id"]: row for row in result["options"]}
    assert options["hf-cpu-basic-pro"]["known_monthly_subtotal_usd_cents"] == 900
    assert options["hf-cpu-basic-pro"]["zero_recurring_allowance_candidate"] is False
    assert options["do-basic-8gib"]["single_reservation_memory_fit"] is True
    assert options["do-basic-8gib"]["dual_reservation_memory_fit"] is False
    assert options["oracle-a1-free"]["architecture_matches_reference"] is False
    assert options["google-e2-micro-free"]["single_reservation_memory_fit"] is False
    assert options["existing-local"]["single_reservation_memory_fit"] is None
    assert all(row["all_in_bill_confirmed"] is False for row in options.values())


def test_memory_target_pass_cannot_authorize_unverified_cloud(catalog):
    rows = fixture_evidence()
    for row in rows[3]["cells"]:
        row["summary"]["resources"]["rss_max_bytes"] = 2 * 1024**3
    for row in rows[4]["steps"][:3]:
        row["result"]["phases"][0]["summary"]["resources"]["rss_max_bytes"] = 2 * 1024**3
    result = design.decide(catalog, design.measured_facts(rows))
    assert "serving_rss_exceeds_2gib_charter" not in result["decision"]["blockers"]
    assert result["decision"]["deployment_eligible"] is False


@pytest.mark.parametrize("value", [True, 1.0, -1, 10**400, None, "1"])
def test_byte_and_money_values_are_bounded_plain_integers(value):
    with pytest.raises(ValueError):
        design.integer(value)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "negative-cost",
        "bool-memory",
        "float-cost",
        "nan-cost",
        "unknown-source",
        "credentials",
        "free-subscription",
        "missing-local",
        "date",
        "schema",
        "architecture",
    ],
)
def test_invalid_catalog_cannot_produce_an_approval(catalog, change):
    row = catalog["options"][1]
    if change == "duplicate":
        catalog["options"].append(copy.deepcopy(row))
    elif change == "negative-cost":
        row["monthly_components_cents"]["compute_within_allowance"] = -1
    elif change == "bool-memory":
        row["ram_bytes"] = True
    elif change == "float-cost":
        row["monthly_components_cents"]["compute_within_allowance"] = 0.0
    elif change == "nan-cost":
        row["monthly_components_cents"]["compute_within_allowance"] = float("nan")
    elif change == "unknown-source":
        row["source_ids"] = ["missing"]
    elif change == "credentials":
        catalog["sources"]["oracle-free"] = "https://secret@example.com/"
    elif change == "free-subscription":
        row["monthly_components_cents"]["membership"] = 900
    elif change == "missing-local":
        catalog["options"] = catalog["options"][1:]
    elif change == "date":
        catalog["checked_on"] = "2026-99-99"
    elif change == "schema":
        row["grant_deployment"] = True
    else:
        row["architecture"] = []
    with pytest.raises(ValueError):
        design.validate_catalog(catalog)


@pytest.mark.parametrize(
    "change", ["manifest", "incomplete", "image", "target", "bool-rss", "storage", "missing-step"]
)
def test_cross_receipt_lineage_and_resource_accounting(change):
    rows = fixture_evidence()
    if change == "manifest":
        rows[2]["identity"] = {**rows[2]["identity"], "manifest_sha256": "c" * 64}
    elif change == "incomplete":
        rows[4]["operational_passed"] = False
    elif change == "image":
        rows[3]["identity"] = {**rows[3]["identity"], "image_id": "sha256:" + "c" * 64}
    elif change == "target":
        rows[4]["policy"] = {"targets": {"rss_bytes": 4 * 1024**3}}
    elif change == "bool-rss":
        rows[3]["cells"][0]["summary"]["resources"]["rss_max_bytes"] = True
    elif change == "storage":
        rows[0]["component_bytes"] = 101
    else:
        rows[4]["steps"].pop()
    with pytest.raises(ValueError):
        design.measured_facts(rows)


def test_assessment_and_publication_are_deterministic_nonoverwriting(design_root):
    result = design.assess(design_root)
    assert result == design.assess(design_root)
    path = design_root / "result.json"
    design.publish(path, result)
    raw = path.read_bytes()
    assert design.read_json(path)["content_sha256"] == design.digest(result)
    with pytest.raises(ValueError, match="Preserve"):
        design.publish(path, result)
    assert path.read_bytes() == raw
    assert not list(path.parent.glob(".deployment-*"))


def test_modified_receipt_cannot_be_repaired_by_resigning(design_root):
    path = design_root / next(iter(design.INPUTS))
    value = design.read_json(path)
    value["complete"] = False
    value["payload_sha256"] = design.digest(
        {k: v for k, v in value.items() if k != "payload_sha256"}
    )
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="pin"):
        design.assess(design_root)


def test_changed_source_during_assessment_prevents_publication(design_root, monkeypatch):
    original = design.evidence

    def changed(root):
        result = original(root)
        (root / design.SOURCE[0]).write_text("changed source", encoding="utf-8")
        return result

    monkeypatch.setattr(design, "evidence", changed)
    with pytest.raises(ValueError, match="changed"):
        design.assess(design_root)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', "[]", '{"a":Infinity}'])
def test_json_rejects_duplicate_nonfinite_and_nonobject_inputs(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        design.read_json(path)


def test_publication_race_does_not_replace_another_receipt(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    link = design.os.link

    def raced(source, target):
        Path(target).write_text("preserve another publisher", encoding="utf-8")
        link(source, target)

    monkeypatch.setattr(design.os, "link", raced)
    with pytest.raises(FileExistsError):
        design.publish(path, {"example": True})
    assert path.read_text(encoding="utf-8") == "preserve another publisher"
    assert not list(tmp_path.glob(".deployment-*"))


@pytest.mark.parametrize("resign", [False, True])
def test_cli_check_rejects_bool_integer_substitution(design_root, monkeypatch, resign):
    result = design.assess(design_root)
    path = design_root / "result.json"
    design.publish(path, result)
    monkeypatch.setattr(design, "assess", lambda: result)
    monkeypatch.setattr("sys.argv", ["assess_deployment.py", "--check", str(path)])
    design.main()
    actual = design.read_json(path)
    actual["decision"]["deployment_eligible"] = 0
    if resign:
        actual["content_sha256"] = design.digest(
            {k: v for k, v in actual.items() if k != "content_sha256"}
        )
    path.write_text(json.dumps(actual), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        design.main()
    assert exc.value.code == 1


def test_existing_local_cannot_claim_arm_qualification(catalog):
    catalog["options"][0]["architecture"] = "arm64"
    with pytest.raises(ValueError):
        design.validate_catalog(catalog)
