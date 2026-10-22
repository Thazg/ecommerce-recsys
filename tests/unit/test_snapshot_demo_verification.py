"""The public identity check must reject source drift and incomplete inventories."""

import copy
import json
import shutil

import pytest

from ecommerce_recsys.artifacts.contract import digest
from scripts import verify_snapshot_demo as verify


@pytest.fixture
def checkout(tmp_path):
    for name in verify.FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(verify.ROOT / name, target)
    data_path = tmp_path / "demo/data/showcase_v1.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data["provenance"]["exporter_sha256_lf"] = verify.file_digest(
        tmp_path / "scripts/export_snapshot_demo.py"
    )
    seal(data_path, data)
    receipt = {
        "schema_version": 1,
        "verification": "local-static-snapshot-explorer-v1",
        "model_manifest_sha256": verify.MANIFEST,
        "files_sha256_lf": {name: verify.file_digest(tmp_path / name) for name in verify.FILES},
        "export_content_sha256": data["content_sha256"],
        "live_inference": False,
        "cloud_deployed": False,
        "deployment_eligible": False,
    }
    path = tmp_path / "receipt.json"
    seal(path, receipt)
    return tmp_path, path, receipt


def seal(path, payload):
    payload["content_sha256"] = digest(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_complete_identity_passes_without_model_bundle(checkout):
    root, path, _ = checkout
    assert not (root / "artifacts").exists()
    assert verify.verify(root, path) == {
        "identity_verified": True,
        "files": len(verify.FILES),
        "model_quality_recomputed": False,
    }


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_unlisted_public_files_or_directories_are_rejected(checkout, kind):
    root, path, _ = checkout
    target = root / "demo" / "private-material"
    if kind == "directory":
        target.mkdir()
    else:
        target.write_text("must never be served", encoding="utf-8")
    with pytest.raises(ValueError, match="public demo inventory"):
        verify.verify(root, path)


@pytest.mark.parametrize(
    "name", ["demo/app.js", "demo/transport.mjs", "scripts/export_snapshot_demo.py"]
)
def test_changed_source_is_rejected(checkout, name):
    root, path, _ = checkout
    (root / name).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        verify.verify(root, path)


@pytest.mark.parametrize("fault", ["missing", "traversal", "private"])
def test_incomplete_or_foreign_receipt_inventory_is_rejected(checkout, fault):
    root, path, receipt = checkout
    if fault == "missing":
        receipt["files_sha256_lf"].pop("demo/app.js")
    else:
        receipt["files_sha256_lf"]["../secret" if fault == "traversal" else ".local/plan.md"] = (
            "a" * 64
        )
    seal(path, receipt)
    with pytest.raises(ValueError, match="inventory"):
        verify.verify(root, path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("cloud_deployed", 0),
        ("live_inference", True),
        ("deployment_eligible", None),
    ],
)
def test_receipt_scope_uses_exact_types(checkout, field, value):
    root, path, receipt = checkout
    receipt[field] = value
    seal(path, receipt)
    with pytest.raises(ValueError, match="identity"):
        verify.verify(root, path)


def test_stale_inference_provenance_rejected_even_with_updated_byte_pin(checkout):
    root, path, receipt = checkout
    data_path = root / "demo/data/showcase_v1.json"
    data = json.loads(data_path.read_text())
    data["provenance"]["inference_code_sha256"] = "0" * 64
    seal(data_path, data)
    receipt["files_sha256_lf"]["demo/data/showcase_v1.json"] = verify.file_digest(data_path)
    receipt["export_content_sha256"] = data["content_sha256"]
    seal(path, receipt)
    with pytest.raises(ValueError, match="provenance"):
        verify.verify(root, path)


def test_receipt_digest_tampering_and_duplicate_keys_rejected(checkout):
    root, path, receipt = checkout
    altered = copy.deepcopy(receipt)
    altered["scope"] = "different"
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="checksum"):
        verify.verify(root, path)
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="Duplicate"):
        verify.verify(root, path)
