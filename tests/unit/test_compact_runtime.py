"""Indexed state must preserve fitted snapshot features and prediction semantics."""

import json
from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest
from test_model_artifacts import bundle_path as bundle_path
from test_model_artifacts import fitted as fitted

from ecommerce_recsys.artifacts import load_bundle
from ecommerce_recsys.artifacts.compact_runtime import _Affinities, load_compact_bundle
from ecommerce_recsys.artifacts.contract import file_sha


@pytest.fixture
def readers(bundle_path):
    pin = file_sha(bundle_path / "model_manifest.json")
    return load_bundle(bundle_path), load_compact_bundle(bundle_path, expected_manifest_sha256=pin)


def test_all_fitted_users_and_cold_match_every_trace_field(readers, bundle_path):
    original, compact = readers
    for reference in json.loads((bundle_path / "references.json").read_text()):
        user = reference["user_id"]
        assert original.trace(user) == compact.trace(user) == reference["trace"]
    for user in [*original.users, None, "absent", 123]:
        assert original.context(user) == compact.context(user)
        for k in (1, 5, 10, 20):
            assert original.recommend(user, k=k) == compact.recommend(user, k=k)


def test_feature_lookup_values_types_and_sparse_semantics_match(readers):
    original, compact = readers
    for name in original.features.__slots__:
        first, second = getattr(original.features, name), getattr(compact.features, name)
        if not isinstance(first, Mapping):
            assert first == second
            continue
        assert dict(first) == dict(second)
        assert first.get("missing") == second.get("missing")
        for key in first:
            if isinstance(first[key], dict):
                assert dict(first[key]) == dict(second[key])
                assert first[key].get("missing", -1) == second[key].get("missing", -1)
            else:
                assert type(first[key]) is type(second[key])
    with pytest.raises(TypeError):
        compact.features.user_events[compact.users[0]] = 0
    with pytest.raises(ValueError, match="read-only"):
        compact.features.user_events.values[0] = 0
    assert all(source.catalog is compact.hybrid.catalog for source in compact.hybrid.sources)
    assert isinstance(compact.arrays["user_factors"], np.memmap)
    assert not compact.arrays["user_factors"].flags.writeable


@pytest.mark.parametrize("empty", [False, True])
def test_sparse_affinity_mapping_handles_order_missing_rows_and_bounds(empty):
    frame = pd.DataFrame(
        [] if empty else [("u2", "z", 9), ("u0", "z", 2), ("u0", "a", 3)],
        columns=["user_id", "category_id", "count"],
    ).astype({"count": "int64"})
    expected = {(u, c): v for u, c, v in frame.itertuples(index=False, name=None)}
    actual = _Affinities(frame, {"u0": 0, "u1": 1, "u2": 2})
    assert dict(actual) == expected
    for key in [(u, c) for u in ("u0", "u1", "u2", "u3") for c in ("a", "z", "zz")]:
        assert actual.get(key, 0) == expected.get(key, 0)
    for key in (None, (), ("u0",), ("u0", "z", "extra")):
        assert actual.get(key) is None
    for array in (actual.indptr, actual.indices, actual.counts):
        assert not array.flags.writeable


@pytest.mark.parametrize("pin", [None, True, "", "0" * 63, "A" * 64])
def test_external_pin_is_required_before_loading(bundle_path, pin):
    with pytest.raises(ValueError, match="external"):
        load_compact_bundle(bundle_path, expected_manifest_sha256=pin)


def test_wrong_pin_and_tampered_component_fail_before_restoration(bundle_path):
    with pytest.raises(ValueError, match="manifest digest"):
        load_compact_bundle(bundle_path, expected_manifest_sha256="0" * 64)
    pin = file_sha(bundle_path / "model_manifest.json")
    with (bundle_path / "weights.npy").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError):
        load_compact_bundle(bundle_path, expected_manifest_sha256=pin)


def test_compact_loader_never_calls_the_original_dictionary_restorer(bundle_path, monkeypatch):
    from ecommerce_recsys.artifacts import runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("Original dictionary restorer must not be used")

    monkeypatch.setattr(runtime, "restore_sources", forbidden)
    compact = load_compact_bundle(
        bundle_path, expected_manifest_sha256=file_sha(bundle_path / "model_manifest.json")
    )
    assert compact.recommend(None).route == "recent_popularity"


def test_existing_http_boundary_accepts_the_explicit_loader(bundle_path):
    from serving_test_support import TestClient, create_fixture_app

    from ecommerce_recsys.serving.contracts import ServiceSettings

    pin = file_sha(bundle_path / "model_manifest.json")
    settings = ServiceSettings(bundle_path, pin)
    expected = load_bundle(bundle_path).recommend("u0", k=5)
    with TestClient(create_fixture_app(settings, loader=load_compact_bundle)) as client:
        assert client.get("/health/ready").status_code == 200
        response = client.post("/v1/recommendations", json={"user_id": "u0", "k": 5})
        assert response.status_code == 200
        assert response.json()["items"] == list(expected.items)
        assert response.json()["route"] == expected.route
