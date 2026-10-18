"""Explicit real-bundle profile; never satisfied by synthetic model fixtures."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ecommerce_recsys.artifacts.contract import verify_inventory
from scripts.release_validation import (
    QUALITY_PATH,
    QUALITY_PIN,
    load_receipt,
    validate_loader,
    validate_quality,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.real_bundle
def test_pinned_producer_numerics_in_an_isolated_loader(request, tmp_path):
    bundle = request.config.getoption("--bundle-path").resolve()
    pin = request.config.getoption("--bundle-manifest-sha256")
    quality = request.config.getoption("--bundle-quality-receipt") or QUALITY_PATH
    quality_pin = request.config.getoption("--bundle-quality-sha256") or QUALITY_PIN
    manifest = verify_inventory(bundle, pin)
    validate_quality(quality, quality_pin, manifest, pin)
    output = request.config.getoption("--bundle-loader-evidence") or tmp_path / "loader.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/verify_model_artifacts.py"),
        str(bundle),
        "--manifest-sha256",
        pin,
        "--quality-receipt",
        str(quality),
        "--output",
        str(output),
    ]
    with (tmp_path / "loader.log").open("wb") as log:
        process = subprocess.run(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            timeout=240,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    assert process.returncode == 0, (
        "Pinned package reference verification failed; inspect private loader log."
    )
    data = load_receipt(output, checksum="payload_sha256")
    validate_loader(data, manifest=manifest, pin=pin, quality_pin=quality_pin)
