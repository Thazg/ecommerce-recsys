"""M9 optional Faiss adapter and pilot checkpoint checks."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.retrieval.two_tower import TwoTowerRetriever
from scripts.benchmark_m9_ann_pilot import CONFIGS, _sha, _validate_checkpoint
from scripts.m9_faiss_adapter import FaissTwoTowerANN


def test_ann_contract_and_exact_parity_when_shortlist_is_exhaustive() -> None:
    pytest.importorskip("faiss")
    torch = pytest.importorskip("torch")

    class ConstantUserModel:
        def encode_user(self, histories):
            return torch.tensor([[1.0, 0.0]] * len(histories))

    catalog = pd.DataFrame({"item_id": ["A", "B", "C", "D"], "category_id": ["x", "x", "x", "x"]})
    exact = TwoTowerRetriever(catalog)
    exact.model = ConstantUserModel()
    exact.max_history = 3
    exact.item_vectors = np.asarray(
        [[1.0, 0.0], [0.0, 1.0], [0.8, 0.6], [0.7, 0.7141428]], dtype=np.float32
    )
    ann = FaissTwoTowerANN(exact, graph_degree=16, ef_construction=200, ef_search=20, max_budget=3)
    context = RetrievalContext("u", ("A", "B", "A"))
    exact_ids = [candidate.item_id for candidate in exact.generate(context, 3)]
    ann_ids = [candidate.item_id for candidate in ann.generate(context, 3)]
    assert ann_ids == exact_ids == ["C", "D"]
    assert [candidate.item_id for candidate in ann.generate(context, 1)] == ann_ids[:1]
    assert [candidate.evidence[0].rank for candidate in ann.generate(context, 3)] == [1, 2]
    assert ann.generate(RetrievalContext(), 3) == []
    exact.model = object()
    with pytest.raises(ValueError, match="stale"):
        ann.generate(context, 3)


def test_pilot_checkpoint_rejects_duplicate_configuration() -> None:
    identity = {
        "policy": {"configs": CONFIGS},
        "policy_sha256": "policy",
        "runner_sha256": "code",
    }
    valid = {
        **identity,
        "results": [],
        "results_sha256": _sha([]),
        "complete": False,
        "decision": "pending",
    }
    round_tripped = json.loads(json.dumps(valid))
    _validate_checkpoint(round_tripped, identity)
    broken = copy.deepcopy(round_tripped)
    broken["results"] = [{"config": CONFIGS[1]}]
    broken["results_sha256"] = _sha(broken["results"])
    with pytest.raises(ValueError, match="configuration"):
        _validate_checkpoint(broken, identity)
