"""Small fitted fixture: real sources, export, loader and child HTTP process."""

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.artifacts.contract import file_sha
from ecommerce_recsys.artifacts.export import export_bundle
from ecommerce_recsys.evaluation.numeric_threads import single_thread_benchmark
from ecommerce_recsys.ranking.dataset import SnapshotFeatures
from ecommerce_recsys.retrieval.base import RetrievalContext
from scripts import benchmark_model_policy as policy
from scripts.build_model_artifacts import producer_reference
from scripts.learned_ranker import PairwiseRanker


@pytest.fixture(scope="session")
@single_thread_benchmark
def fitted_snapshot(tmp_path_factory):
    rows = [
        (f"u{u:02}", f"i{i:02}", 100 + i, "view")
        for u in range(12)
        for i in range(40)
        if (u + i) % 4 == 0
    ]
    # One exhaustive context verifies that empty output is legitimate.
    rows += [("exhausted", f"i{i:02}", 100 + i, "view") for i in range(40)]
    train = pd.DataFrame(rows, columns=["user_id", "item_id", "timestamp", "event_type"])
    catalog = pd.DataFrame(
        {"item_id": [f"i{i:02}" for i in range(40)], "category_id": [None, "a", "b", "c"] * 10}
    )
    configs = {
        "als": {"factors": 3, "iterations": 2, "regularization": 0.01},
        "item_knn": {"shrinkage_lambda": 100.0},
    }
    sources, hybrids, _, _ = policy.ranker.build_sources(train, catalog, 150, configs)
    features = SnapshotFeatures.from_frames(train, catalog, 150)
    ranker = PairwiseRanker(np.linspace(-0.1, 0.2, 32), np.linspace(0.5, 2.0, 32), 1.0, 1, True)
    predictor = policy.OfflinePredictor(
        sources=sources,
        hybrids=hybrids,
        features=features,
        model=ranker,
        fold_index=9,
        categories=dict(catalog.itertuples(index=False, name=None)),
    )
    contexts = [
        RetrievalContext(str(user), tuple(frame["item_id"]))
        for user, frame in train.groupby("user_id")
    ]
    references = [producer_reference(predictor, context) for context in contexts]
    references.append(producer_reference(predictor, RetrievalContext()))
    path = export_bundle(
        tmp_path_factory.mktemp("fitted-snapshot"),
        "integration-fixture-v1",
        sources=sources,
        features=features,
        weights=ranker.weights,
        scales=ranker.scales,
        snapshot={
            "fold_index": 9,
            "cutoff": 150,
            "ranker_label_cutoff": 100,
            "users": train["user_id"].nunique(),
            "items": len(catalog),
            "events": len(train),
            "configs": configs,
            "seeds": {"als_fit": 42, "ranker_negative_sampling": 42},
        },
        provenance={"fixture": "synthetic fitted sources; not Retailrocket quality evidence"},
        references=references,
    )
    return path, file_sha(path / "model_manifest.json"), references, train, catalog
