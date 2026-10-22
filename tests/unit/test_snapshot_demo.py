"""A public showcase must remain a finite, verified projection of sealed outputs."""

import copy
import json
from types import SimpleNamespace

import pytest

from ecommerce_recsys.artifacts.contract import digest
from ecommerce_recsys.artifacts.runtime import evidence_digest
from ecommerce_recsys.retrieval.base import Candidate, RetrievalContext, SourceEvidence
from scripts import export_snapshot_demo as demo


def fixture_bundle():
    def candidate(item, source):
        return Candidate(item, 1.0, (SourceEvidence(source, 1.0, int(item) // 10),))

    warm_pool = [candidate("10", "als"), candidate("20", "item_knn")]
    cold_pool = [candidate("10", "recent_popularity"), candidate("20", "recent_popularity")]
    private = "PRIVATE-REFERENCE-USER"

    def trace(user):
        pool = warm_pool if user is not None else cold_pool
        return {
            "pool": ["10", "20"],
            "output": ["20", "10"] if user is not None else ["10", "20"],
            "evidence_sha256": evidence_digest(pool),
            "features_sha256": "a" * 64,
            "scores_sha256": "b" * 64,
            "route": "hybrid_learned" if user is not None else "recent_popularity",
        }

    bundle = SimpleNamespace(
        user_index={private: 0},
        trace=trace,
        context=lambda user: RetrievalContext(user, ("99",) if user is not None else ()),
        hybrid=SimpleNamespace(generate=lambda context, limit: warm_pool),
        cold=SimpleNamespace(generate=lambda context, limit: cold_pool),
        items=["10", "20", "99"],
        features=SimpleNamespace(categories={"10": "3"}),
    )
    refs = [{"user_id": private, "trace": trace(private)} for _ in range(100)]
    refs.append({"user_id": None, "trace": trace(None)})
    return bundle, refs


def test_projection_is_deterministic_private_and_preserves_both_orders():
    bundle, refs = fixture_bundle()
    profiles = demo.build_profiles(bundle, refs)
    assert profiles == demo.build_profiles(bundle, refs)
    assert "PRIVATE-REFERENCE-USER" not in json.dumps(profiles)
    assert "user_id" not in json.dumps(profiles)
    assert [p["id"] for p in profiles] == [
        "profile-01",
        "profile-02",
        "profile-03",
        "profile-04",
        "cold-start",
    ]
    assert profiles[0]["orders"] == {"learned": ["20", "10"], "rrf": ["10", "20"]}
    assert profiles[-1]["orders"] == {"recent": ["10", "20"]}
    assert profiles[0]["history_items"] == 1
    assert profiles[0]["items"][1]["category_id"] is None


@pytest.mark.parametrize("field", ["pool", "output", "evidence_sha256", "scores_sha256"])
def test_any_sealed_trace_mismatch_aborts(field):
    bundle, refs = fixture_bundle()
    refs[25]["trace"][field] = [] if field in {"pool", "output"} else "c" * 64
    with pytest.raises(ValueError, match="sealed reference"):
        demo.build_profiles(bundle, refs)


@pytest.mark.parametrize("fault", ["seen", "duplicate", "foreign", "empty", "evidence"])
def test_invalid_pool_aborts_even_if_sealed_reference_is_matching(fault):
    bundle, refs = fixture_bundle()
    original = bundle.hybrid.generate(None, 1000)
    pool = list(original)
    if fault == "seen":
        bundle.context = lambda user: RetrievalContext(user, ("10",))
    elif fault == "duplicate":
        pool.append(pool[0])
    elif fault == "foreign":
        bundle.items = ["20", "99"]
    elif fault == "empty":
        pool = []
    else:
        pool = [Candidate("10", 2.0, original[0].evidence), original[1]]
    bundle.hybrid.generate = lambda context, limit: pool
    trace = copy.deepcopy(refs[0]["trace"])
    trace["pool"] = [candidate.item_id for candidate in pool]
    if fault != "evidence":
        trace["evidence_sha256"] = evidence_digest(pool)
    original_trace = bundle.trace
    bundle.trace = lambda user: trace if user is not None else original_trace(None)
    for ref in refs[:-1]:
        ref["trace"] = trace
    with pytest.raises(ValueError, match="inventory"):
        demo.build_profiles(bundle, refs)


def test_reference_inventory_and_explicit_cold_are_required():
    bundle, refs = fixture_bundle()
    with pytest.raises(ValueError, match="inventory"):
        demo.build_profiles(bundle, refs[:-1])
    refs[-1]["user_id"] = "unrecognized-user"
    original_trace = bundle.trace
    bundle.trace = lambda user: original_trace(None if user == "unrecognized-user" else user)
    with pytest.raises(ValueError, match="route"):
        demo.build_profiles(bundle, refs)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_public_evidence_must_be_finite(value):
    candidate = SimpleNamespace(item_id="10", score=value, evidence=())
    with pytest.raises(ValueError, match="Nonfinite"):
        demo.public_item(candidate, 1, {})


@pytest.mark.parametrize("item,category", [("<script>", None), ("1", "title"), ("1", 3)])
def test_anonymous_codes_not_invented_metadata(item, category):
    candidate = SimpleNamespace(item_id=item, score=1.0, evidence=())
    with pytest.raises(ValueError, match="code"):
        demo.public_item(candidate, 1, {item: category})


def test_atomic_publication_never_replaces_existing_file(tmp_path):
    path = tmp_path / "showcase.json"
    payload = {"examples": 5, "content_sha256": digest({"examples": 5})}
    demo.write_once(path, payload)
    first = path.read_bytes()
    with pytest.raises(FileExistsError):
        demo.write_once(path, {"examples": 6})
    assert path.read_bytes() == first
    assert list(tmp_path.iterdir()) == [path]


def test_failed_serialization_does_not_publish_or_leave_temporary_file(tmp_path):
    with pytest.raises(ValueError):
        demo.write_once(tmp_path / "bad.json", {"value": float("nan")})
    assert not list(tmp_path.iterdir())


def test_existing_output_refuses_before_model_load(tmp_path, monkeypatch):
    output = tmp_path / "existing.json"
    output.write_text("preserve", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("Existing output must fail before expensive model loading")

    monkeypatch.setattr(demo, "load_bundle", forbidden)
    with pytest.raises(FileExistsError):
        demo.export(tmp_path / "no-bundle", output)


def test_public_source_names_are_allowlisted():
    candidate = Candidate("10", 1.0, (SourceEvidence("private-path", 1.0, 1),))
    with pytest.raises(ValueError, match="evidence"):
        demo.public_item(candidate, 1, {})


@pytest.mark.parametrize("suffix", ["showcase.json", "nested/showcase.json", "."])
def test_output_inside_bundle_is_rejected_before_loading(tmp_path, monkeypatch, suffix):
    root = tmp_path / "bundle"
    root.mkdir()

    def forbidden(*args, **kwargs):
        pytest.fail("Contained output must fail before model load")

    monkeypatch.setattr(demo, "load_bundle", forbidden)
    with pytest.raises(ValueError, match="outside"):
        demo.export(root, root / suffix)
    assert not list(root.iterdir())


def test_output_symlink_parent_cannot_alias_bundle(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account lacks directory-symlink privilege")
    with pytest.raises(ValueError, match="outside"):
        demo.check_output_location(root, alias / "showcase.json")


def test_output_sibling_is_allowed(tmp_path):
    root = tmp_path / "bundle"
    assert (
        demo.check_output_location(root, tmp_path / "bundle-demo" / "out.json")
        == (tmp_path / "bundle-demo" / "out.json").resolve()
    )
