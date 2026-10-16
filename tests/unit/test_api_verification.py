"""Pins and immutable receipts for the real HTTP verification command."""

import json
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from ecommerce_recsys.artifacts.contract import digest, file_sha, write_json  # noqa: E402
from scripts import verify_recommendation_api as verifier  # noqa: E402
from scripts.verify_recommendation_api import (  # noqa: E402
    Probe,
    compare_output,
    publish_receipt,
    reference_inputs,
    verify_openapi,
)


def test_reference_component_and_external_pin_are_checked(tmp_path):
    rows = [
        {"user_id": "1", "trace": {"route": "hybrid_learned", "output": ["a"]}},
        {"user_id": None, "trace": {"route": "recent_popularity", "output": ["b"]}},
    ]
    write_json(tmp_path / "references.json", rows)
    manifest = {
        "bundle_version": "fixture",
        "snapshot": {"cutoff": 9},
        "components": {"references.json": {"sha256": file_sha(tmp_path / "references.json")}},
    }
    write_json(tmp_path / "model_manifest.json", manifest)
    pin = file_sha(tmp_path / "model_manifest.json")
    assert reference_inputs(tmp_path, pin)[1] == rows
    with pytest.raises(ValueError, match="pin"):
        reference_inputs(tmp_path, "0" * 64)
    write_json(tmp_path / "references.json", rows[:1])
    with pytest.raises(ValueError, match="Reference component"):
        reference_inputs(tmp_path, pin)


def test_response_parity_and_receipt_cannot_be_overwritten(tmp_path):
    row = {"trace": {"route": "hybrid_learned", "output": ["a", "b"]}}
    manifest = {"bundle_version": "fixture", "snapshot": {"cutoff": 9}}
    actual = {
        "request_id": "id",
        "items": ["a"],
        "route": "hybrid_learned",
        "bundle_version": "fixture",
        "cutoff": 9,
    }
    assert compare_output(actual, row, manifest, 1)["items"] == ["a"]
    with pytest.raises(ValueError, match="differs"):
        compare_output({**actual, "items": ["b"]}, row, manifest, 1)
    path = tmp_path / "receipt.json"
    publish_receipt(path, {"parity": True})
    assert json.loads(path.read_text()) == {
        "parity": True,
        "content_sha256": digest({"parity": True}),
    }
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Preserve"):
        publish_receipt(path, {"parity": False})
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "manifest", [{}, [], {"snapshot": {}}, {"bundle_version": "x", "snapshot": {"cutoff": True}}]
)
def test_malformed_manifest_has_descriptive_value_error(tmp_path, manifest):
    write_json(tmp_path / "model_manifest.json", manifest)
    write_json(tmp_path / "references.json", [])
    with pytest.raises(ValueError, match="manifest contract"):
        reference_inputs(tmp_path, file_sha(tmp_path / "model_manifest.json"))


@pytest.mark.parametrize(
    "status,body,message",
    [
        (500, b"<html>private traceback</html>", "HTTP status differs"),
        (200, b"<html>private input</html>", "Invalid JSON response"),
        (200, b"[]", "JSON object"),
    ],
)
def test_probe_fails_cleanly_on_html_or_wrong_json_shape(status, body, message):
    probe = Probe(1)
    probe.connection = SimpleNamespace(
        request=lambda *a, **k: None,
        getresponse=lambda: SimpleNamespace(status=status, read=lambda: body),
    )
    with pytest.raises(ValueError, match=message) as error:
        probe.call("GET", "/health/ready")
    assert "private" not in str(error.value)


def test_malformed_openapi_is_a_contract_failure():
    with pytest.raises(ValueError, match="OpenAPI"):
        verify_openapi({})


def test_verifier_cli_aborts_without_traceback_or_partial_receipt(tmp_path, monkeypatch, capsys):
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify-http",
            "--bundle",
            str(tmp_path),
            "--manifest-sha256",
            "a" * 64,
            "--output",
            str(output),
        ],
    )

    def fail(*args, **kwargs):
        raise ValueError("Invalid JSON response for GET /health/ready.")

    monkeypatch.setattr(verifier, "verify", fail)
    with pytest.raises(SystemExit) as error:
        verifier.main()
    assert error.value.code == 1
    assert "HTTP verification failed" in capsys.readouterr().err
    assert not output.exists()
