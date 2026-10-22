"""Reproduce an offline hosting decision; never provision or authorize deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CATALOG = "benchmarks/deployment/hosting_options_v1.json"
SOURCE = ("scripts/assess_deployment.py", "tests/unit/test_deployment_assessment.py")
INPUTS = {
    "benchmarks/artifacts/fold09_v1.json": "12a954fb8535ff69ba767fde9b7c4c949f3aec421dbba995ba1a8137ad2098e8",
    "benchmarks/containers/linux_snapshot_boundary_validation_v1.json": "cdc11edf294a5ddd3d707fe7c3c565b2f53db1e0d5ecb43712174bddb05637ec",
    "benchmarks/release/release_workflow_preflight_validation_v1.json": "7b37d58c41c34cc7011adcf3c0ed39e29512aaf91b1a97b893a689bbde86d55d",
    "benchmarks/performance/http_capacity_boundary_validation_v1.json": "d239ecad08f244fb58b28cbdbf545f3db4789f5f36d1c9cbbb119a65d022aaf1",
    "benchmarks/reliability/service_resilience_boundary_validation_v1.json": "ef0bc9b6b927a9ce70f24c96704d92a2db00df2c27fc0c3cbe91dd2eee1d0408",
}
POLICY = {
    "version": "deployment-design-v1",
    "preference": "free_first",
    "current_mode": "existing_local_only",
    "preferred_free_candidate": "oracle-a1-free",
    "qualified_architecture": "amd64",
    "charter_rss_bytes": 2 * 1024**3,
    "container_reservation_bytes": 4 * 1024**3,
    "host_reserve_bytes": 2 * 1024**3,
    "retained_bundle_versions": 3,
    "staging_bundle_copies": 1,
    "planned_release": "maintenance_stop_start",
    "provider_account_verified": False,
    "target_host_qualified": False,
    "public_exposure_approved": False,
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def integer(value, maximum=2**63 - 1, *, positive=False):
    if type(value) is not int or not (0 < value if positive else 0 <= value) or value > maximum:
        raise ValueError("Expected a bounded plain integer.")
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def file_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("Expected bounded regular JSON input.")
    with path.open("rb") as stream:
        raw = stream.read(4 * 1024**2 + 1)
    if len(raw) > 4 * 1024**2:
        raise ValueError("Input grew beyond its byte budget.")
    return raw


def read_json(path, expected_sha=None):
    raw = file_bytes(path)
    if expected_sha is not None and sha(raw) != expected_sha:
        raise ValueError("Frozen deployment evidence pin differs.")

    def invalid(_):
        raise ValueError("Nonfinite JSON input.")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid JSON input.") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("Expected bounded nonempty text.")


def validate_catalog(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "checked_on", "currency", "sources", "options"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["currency"] != "USD"
        or not isinstance(value["checked_on"], str)
        or date.fromisoformat(value["checked_on"]).isoformat() != value["checked_on"]
        or not isinstance(value["sources"], dict)
        or not value["sources"]
        or not isinstance(value["options"], list)
        or not 1 <= len(value["options"]) <= 20
    ):
        raise ValueError("Unsupported hosting catalog.")
    for key, url in value["sources"].items():
        text(key)
        text(url)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Sources require public HTTPS URLs without credentials.")
    seen = set()
    for row in value["options"]:
        if not isinstance(row, dict) or set(row) != {
            "id",
            "label",
            "region",
            "architecture",
            "ram_bytes",
            "billing_class",
            "monthly_components_cents",
            "source_ids",
            "conditions",
            "exclusions",
            "risks",
        }:
            raise ValueError("Unsupported hosting option schema.")
        if not isinstance(row["id"], str) or not re.fullmatch(r"[a-z0-9-]{1,64}", row["id"]):
            raise ValueError("Invalid option identifier.")
        if row["id"] in seen:
            raise ValueError("Duplicate hosting option.")
        seen.add(row["id"])
        for name in ("label", "region"):
            text(row[name])
        if not isinstance(row["architecture"], str) or not isinstance(row["billing_class"], str):
            raise ValueError("Architecture and billing class must be strings.")
        if row["architecture"] not in {"amd64", "arm64", "unconfirmed"} or row[
            "billing_class"
        ] not in {
            "existing_local",
            "conditional_free",
            "subscription",
            "paid",
        }:
            raise ValueError("Unknown architecture or billing class.")
        local = row["billing_class"] == "existing_local"
        if local != (row["id"] == "existing-local"):
            raise ValueError("Only the existing local route can omit provider resources.")
        if local:
            if (
                row["ram_bytes"] is not None
                or row["architecture"] != POLICY["qualified_architecture"]
            ):
                raise ValueError("Local capacity is unmeasured and its reference remains amd64.")
        else:
            integer(row["ram_bytes"], positive=True)
        costs = row["monthly_components_cents"]
        if not isinstance(costs, dict) or not 1 <= len(costs) <= 12:
            raise ValueError("Missing bounded cost components.")
        for name, amount in costs.items():
            text(name)
            integer(amount, 1_000_000)
        if row["billing_class"] in {"conditional_free", "existing_local"} and sum(costs.values()):
            raise ValueError("A free allowance cannot hide a recurring subscription.")
        for name in ("source_ids", "conditions", "exclusions", "risks"):
            items = row[name]
            if (
                not isinstance(items, list)
                or len(items) > 30
                or (not items and name != "source_ids")
            ):
                raise ValueError("Missing hosting conditions, exclusions or risks.")
            for item in items:
                text(item)
            if len(set(items)) != len(items):
                raise ValueError("Duplicate hosting metadata.")
        if not set(row["source_ids"]) <= set(value["sources"]) or (
            not local and not row["source_ids"]
        ):
            raise ValueError("Missing provider source attribution.")
    if "existing-local" not in seen:
        raise ValueError("The local-only decision requires its explicit existing route.")
    return value


def evidence(root):
    rows = []
    for name, pin in INPUTS.items():
        value = read_json(root / name, expected_sha=pin)
        checksum = "payload_sha256" if name.endswith("fold09_v1.json") else "content_sha256"
        if value.get(checksum) != digest({k: v for k, v in value.items() if k != checksum}):
            raise ValueError("Frozen receipt content checksum differs.")
        rows.append(value)
    return rows


def measured_facts(rows):
    bundle, container, release, capacity, resilience = rows
    manifest = bundle["identity"]["manifest_sha256"]
    if (
        bundle.get("complete") is not True
        or bundle.get("loaded_quality_matches_policy") is not True
        or container.get("qualification_passed") is not True
        or release.get("operational_passed") is not True
        or capacity.get("assessment_completed") is not True
        or resilience.get("operational_passed") is not True
        or len(capacity["cells"]) != 4
        or [r["step"] for r in resilience["steps"]]
        != [
            "sustained",
            "burst-recovery",
            "memory-pressure",
            "client-disconnect",
            "inflight-drain",
            "startup-bad-pin",
            "startup-missing",
            "startup-corrupt",
            "release-recovery",
        ]
        or any(r["identity"]["manifest_sha256"] != manifest for r in rows[1:])
        or any(r.get("deployment_eligible") is not False for r in rows[1:])
        or capacity["identity"]["image_id"] != container["identity"]["image_id"]
        or release["identity"]["image_id"] != container["identity"]["image_id"]
        or container["resource_policy"]["memory_limit_bytes"]
        != POLICY["container_reservation_bytes"]
        or any(r["policy"]["targets"]["rss_bytes"] != POLICY["charter_rss_bytes"] for r in rows[3:])
    ):
        raise ValueError("Incomplete or inconsistent upstream deployment evidence.")
    windows = [r["summary"] for r in capacity["cells"]] + [
        p["summary"] for r in resilience["steps"][:3] for p in r["result"]["phases"]
    ]
    rss = max(integer(r["resources"]["rss_max_bytes"], positive=True) for r in windows)
    sizes = [integer(c["bytes"], positive=True) for c in bundle["components"].values()]
    component_bytes = integer(bundle["component_bytes"], positive=True)
    if not sizes or sum(sizes) != component_bytes:
        raise ValueError("Bundle component storage accounting differs.")
    return {
        "manifest_sha256": manifest,
        "qualified_image_id": container["identity"]["image_id"],
        "qualified_architecture": POLICY["qualified_architecture"],
        "observed_serving_rss_max_bytes": rss,
        "charter_rss_met": rss <= POLICY["charter_rss_bytes"],
        "single_container_host_floor_bytes": POLICY["container_reservation_bytes"]
        + POLICY["host_reserve_bytes"],
        "dual_container_host_floor_bytes": 2 * POLICY["container_reservation_bytes"]
        + POLICY["host_reserve_bytes"],
        "bundle_component_bytes": component_bytes,
        "retained_and_staging_component_bytes": component_bytes
        * (POLICY["retained_bundle_versions"] + POLICY["staging_bundle_copies"]),
        "local_uncached_4rps_rejection_fraction": capacity["cells"][1]["summary"][
            "rejection_fraction"
        ],
        "local_sustained_successes": resilience["steps"][0]["result"]["phases"][0]["summary"][
            "successes"
        ],
    }


def decide(catalog, facts):
    validate_catalog(catalog)
    options = []
    for row in sorted(catalog["options"], key=lambda r: r["id"]):
        ram = row["ram_bytes"]
        subtotal = sum(row["monthly_components_cents"].values())
        options.append(
            {
                "id": row["id"],
                "known_monthly_subtotal_usd_cents": subtotal,
                "zero_recurring_allowance_candidate": row["billing_class"] == "conditional_free"
                and subtotal == 0,
                "single_reservation_memory_fit": None
                if ram is None
                else ram >= facts["single_container_host_floor_bytes"],
                "dual_reservation_memory_fit": None
                if ram is None
                else ram >= facts["dual_container_host_floor_bytes"],
                "architecture_matches_reference": row["architecture"]
                == facts["qualified_architecture"],
                "all_in_bill_confirmed": False,
                "provider_account_verified": False,
                "target_host_qualified": False,
                "deployment_eligible": False,
            }
        )
    preferred = next(
        (
            r
            for r in options
            if r["id"] == POLICY["preferred_free_candidate"]
            and r["zero_recurring_allowance_candidate"]
            and r["single_reservation_memory_fit"]
        ),
        None,
    )
    blockers = [
        "target_host_and_architecture_unqualified",
        "provider_account_capacity_and_free_allowances_unverified",
        "public_tls_proxy_auth_and_rate_contract_unimplemented",
        "private_artifact_registry_and_secret_delivery_unverified",
        "target_host_workload_monitoring_and_restore_unverified",
    ]
    if not facts["charter_rss_met"]:
        blockers.insert(0, "serving_rss_exceeds_2gib_charter")
    return {
        "options": options,
        "decision": {
            "design_completed": True,
            "execution_mode": POLICY["current_mode"],
            "preferred_free_investigation": preferred["id"] if preferred else None,
            "approved_cloud_host": None,
            "cloud_resource_created": False,
            "budget_waiver": False,
            "deployment_eligible": False,
            "blockers": blockers,
        },
    }


def assess(root=ROOT):
    snapshot = {name: sha(file_bytes(root / name)) for name in (*SOURCE, CATALOG, *INPUTS)}
    catalog = validate_catalog(read_json(root / CATALOG, expected_sha=snapshot[CATALOG]))
    facts = measured_facts(evidence(root))
    if any(sha(file_bytes(root / name)) != pin for name, pin in snapshot.items()):
        raise ValueError("Deployment design input/source changed during assessment.")
    return {
        "schema_version": 1,
        "assessment": POLICY["version"],
        "checked_on": catalog["checked_on"],
        "identity": {
            "source_sha256": {name: snapshot[name] for name in SOURCE},
            "catalog_sha256": snapshot[CATALOG],
            "upstream_sha256": dict(INPUTS),
            "policy_sha256": digest(POLICY),
        },
        "policy": dict(POLICY),
        "measured_facts": facts,
        **decide(catalog, facts),
        "limits": [
            "Offline design arithmetic, not a host performance or deployment qualification.",
            "Advertised allowances are dated, conditional and unverified for the operator's account.",
            "Known USD subtotals exclude itemized variable costs; no all-in bill or spending cap is certified.",
            "Host reservations differ from measured RSS; more RAM does not waive the 2GiB process target.",
            "Model component storage excludes manifest overhead, images, OS, logs and provider billing units.",
        ],
    }


def publish(path, result):
    if path.exists() or path.is_symlink():
        raise ValueError("Preserve existing deployment assessments; choose a new path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".deployment-", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {**result, "content_sha256": digest(result)}, stream, indent=2, allow_nan=False
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args()
    try:
        result = assess()
        if args.check:
            actual = read_json(args.check)
            payload = {k: v for k, v in actual.items() if k != "content_sha256"}
            if actual.get("content_sha256") != digest(payload) or digest(payload) != digest(result):
                raise ValueError("Deployment assessment differs from current inputs/source/policy.")
        else:
            publish(args.output, result)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        parser.exit(
            1, "Deployment assessment failed; preserve inputs and inspect local evidence.\n"
        )
    print(json.dumps({"design_completed": True, "deployment_eligible": False}))


if __name__ == "__main__":
    main()
