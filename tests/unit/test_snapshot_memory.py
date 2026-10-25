"""Memory evidence rejects incomplete parity, invalid resources and overwritten output."""

import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import profile_snapshot_memory as profile

PIN = "a" * 64


def result(reader="original"):
    return {
        "reader": reader,
        "manifest_sha256": PIN,
        "runtime": {"python": "3.13.15"},
        "parity_passed": True,
        "reference_requests": 101,
        "warm_requests": 100,
        "cold_requests": 1,
        "load_seconds_including_imports": 1.0,
        "ready_rss_bytes": 100,
        "after_references_rss_bytes": 110,
        "load_peak_rss_bytes": 200,
        "inference_peak_rss_bytes": 110,
        "sampled_peak_rss_bytes": 200,
        "sample_count": 30,
        "sample_span_seconds": 1.4,
        "maximum_sample_gap_seconds": 0.05,
        "reference_trace_seconds": {"warm": 0.2, "cold": 0.001},
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("parity_passed", False),
        ("parity_passed", 1),
        ("reference_requests", 100),
        ("warm_requests", True),
        ("cold_requests", 2),
        ("manifest_sha256", "b" * 64),
        ("ready_rss_bytes", True),
        ("sample_count", 1),
        ("sample_count", 2),
        ("sample_span_seconds", float("nan")),
        ("load_seconds_including_imports", float("inf")),
        ("maximum_sample_gap_seconds", 0.21),
        ("sampled_peak_rss_bytes", 199),
        ("inference_peak_rss_bytes", 109),
        ("reference_trace_seconds", {"warm": 1}),
        ("reference_trace_seconds", {"warm": 2.0, "cold": 0.001}),
    ],
)
def test_incomplete_or_inconsistent_worker_results_are_rejected(key, value):
    record = result()
    record[key] = value
    with pytest.raises(ValueError):
        profile.validate_result(record, "original", PIN)


def test_failed_memory_budget_remains_a_recorded_outcome():
    original, compact = result(), result("compact")
    compact["inference_peak_rss_bytes"] = profile.POLICY["rss_target_bytes"] + 1
    compact["sampled_peak_rss_bytes"] = compact["inference_peak_rss_bytes"]
    record = profile.assessment(original, compact, PIN, {"source": "hash"})
    assert record["compact_loaded_memory_target_passed"] is False
    assert record["deployment_eligible"] is False
    assert record["http_measured"] is False
    assert record["same_host_exact_parity"] is True


def test_reader_order_or_differing_environments_cannot_be_pooled():
    original, compact = result(), result("compact")
    with pytest.raises(ValueError):
        profile.assessment(compact, original, PIN, {})
    compact["runtime"] = {"python": "3.13.16"}
    with pytest.raises(ValueError, match="runtime"):
        profile.assessment(original, compact, PIN, {})


def test_publication_is_exclusive_and_preserves_prior_evidence(tmp_path):
    record = profile.assessment(result(), result("compact"), PIN, {})
    path = tmp_path / "receipt.json"
    profile.publish(path, record)
    first = path.read_bytes()
    with pytest.raises(FileExistsError):
        profile.publish(path, record)
    assert path.read_bytes() == first
    assert not list(tmp_path.glob("*.tmp"))
    invalid = copy.deepcopy(record)
    invalid["deployment_eligible"] = True
    with pytest.raises(ValueError, match="sealed"):
        profile.publish(tmp_path / "invalid.json", invalid)
    assert json.loads(first)["deployment_eligible"] is False


def test_saved_receipt_rejects_new_source_and_resealed_claims(tmp_path, monkeypatch):
    from ecommerce_recsys.artifacts import contract

    monkeypatch.setattr(contract, "verify_inventory", lambda *args: {})
    monkeypatch.setattr(profile, "sources", lambda: {"source": "original"})
    record = profile.assessment(result(), result("compact"), PIN, profile.sources())
    path = tmp_path / "receipt.json"
    profile.publish(path, record)
    assert profile.check_receipt(tmp_path, PIN, path) == record
    duplicate = json.dumps(record).replace(
        '"schema_version": 1', '"schema_version": 0, "schema_version": 1'
    )
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        profile.check_receipt(tmp_path, PIN, path)
    altered = copy.deepcopy(record)
    altered["deployment_eligible"] = True
    altered["content_sha256"] = profile.digest(
        {k: v for k, v in altered.items() if k != "content_sha256"}
    )
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        profile.check_receipt(tmp_path, PIN, path)
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(profile, "sources", lambda: {"source": "changed"})
    with pytest.raises(ValueError, match="stale"):
        profile.check_receipt(tmp_path, PIN, path)


def test_timed_out_owned_worker_is_killed_and_reaped(tmp_path, monkeypatch):
    class Child:
        pid = 123
        returncode = None
        killed = False
        calls = 0

        def communicate(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("owned-worker", 1)
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

        def poll(self):
            return self.returncode

    child = Child()
    monkeypatch.setattr(profile.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(
        profile.psutil,
        "Process",
        lambda pid: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=100)),
    )
    with pytest.raises(subprocess.TimeoutExpired):
        profile.run_reader("original", tmp_path, PIN)
    assert child.killed
    assert child.calls == 2


@pytest.mark.parametrize("stage", ["inspection", "thread_start"])
def test_sampler_setup_failure_still_reaps_the_owned_worker(tmp_path, monkeypatch, stage):
    child = SimpleNamespace(pid=123, returncode=None, killed=False, reaped=False)

    def kill():
        child.killed, child.returncode = True, -9

    def communicate(**kwargs):
        child.reaped = True
        return b"", b""

    def fail(*args, **kwargs):
        raise RuntimeError("controlled sampler setup failure")

    child.kill, child.communicate = kill, communicate
    child.poll = lambda: child.returncode
    monkeypatch.setattr(profile.subprocess, "Popen", lambda *args, **kwargs: child)
    if stage == "inspection":
        monkeypatch.setattr(profile.psutil, "Process", fail)
    else:
        monkeypatch.setattr(profile.psutil, "Process", lambda pid: object())
        monkeypatch.setattr(profile.threading.Thread, "start", fail)
    with pytest.raises(RuntimeError, match="sampler setup"):
        profile.run_reader("original", tmp_path, PIN)
    assert child.killed and child.reaped


@pytest.mark.parametrize("relative", ["missing/receipt.json", "receipt.txt"])
def test_invalid_output_is_rejected_before_loading_models(tmp_path, monkeypatch, relative):
    def forbidden(*args):
        raise AssertionError("Invalid output must be rejected before measuring")

    monkeypatch.setattr(profile, "assess", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "profile",
            "--bundle",
            str(tmp_path),
            "--manifest-sha256",
            PIN,
            "--output",
            str(tmp_path / relative),
        ],
    )
    with pytest.raises(SystemExit) as error:
        profile.main()
    assert error.value.code == 2
