"""Capacity measurement through an actually fitted snapshot child HTTP process."""

import pytest
from service_process import SnapshotServer

from scripts import http_capacity_workload as workload


@pytest.mark.parametrize("cached", [False, True])
def test_fitted_capacity_loop_reconciles_real_http(fitted_snapshot, tmp_path, monkeypatch, cached):
    bundle, pin, references, _, _ = fitted_snapshot
    import json

    manifest = json.loads((bundle / "model_manifest.json").read_text(encoding="utf-8"))
    # Only the fixture's duration changes; real CLI always uses the frozen policy.
    monkeypatch.setitem(workload.POLICY, "duration_seconds", 5)
    cell = {"name": "fitted-fixture", "rate": 2, "concurrency": 4, "cached": cached}
    with SnapshotServer(bundle, pin, tmp_path / "capacity.log", cached=cached) as server:
        result = workload.run_profile(
            references, manifest, pin, cell, port=server.port, process_id=server.process.pid
        )
        assert result["summary"]["offered"] == 10
        assert result["summary"]["successes"] == 10
        assert result["telemetry_delta"]["posts"] == 10
        assert result["telemetry_delta"]["primary"] == (0 if cached else 10)
        assert result["telemetry_delta"]["hits"] == (10 if cached else 0)
        assert result["pre_references"] == result["post_references"] == len(references)
        assert result["parity_passed"]
