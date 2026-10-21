"""Fitted child HTTP traffic through the resilience driver without model mocks."""

import json

import pytest
from service_process import SnapshotServer

from scripts import service_resilience_workload as work


@pytest.mark.parametrize("pressure", [0, 8 * 1024**2])
def test_fitted_phased_load_recovery_and_memory_occupancy(fitted_snapshot, tmp_path, pressure):
    bundle, pin, references, _, _ = fitted_snapshot
    manifest = json.loads((bundle / "model_manifest.json").read_text(encoding="utf-8"))
    # Only fixtures supply shorter/smaller cells; the real CLI exposes the fixed matrix.
    cell = {
        "name": "fitted-resilience",
        "pressure_bytes": pressure,
        "phases": [{"name": "quiet-fixture", "seconds": 5, "rate": 2, "concurrency": 4}],
    }
    with SnapshotServer(bundle, pin, tmp_path / "resilience.log") as server:
        result = work.run_load(
            references, manifest, pin, cell, port=server.port, process_id=server.process.pid
        )
        assert result["parity_passed"]
        assert result["pre_references"] == result["post_references"] == len(references)
        phase = result["phases"][0]
        work.validate_window(phase, cell["phases"][0], references)
        assert phase["summary"]["successes"] == phase["telemetry_delta"]["primary"] == 10
        assert phase["recovery"]["references"] == 2
        occupied = result["pressure"]
        assert occupied["allocated_bytes"] == pressure
        if pressure:
            assert (
                occupied["driver_rss_occupied_bytes"] - occupied["driver_rss_before_bytes"]
                >= 0.9 * pressure
            )
