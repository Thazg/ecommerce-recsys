import numpy as np
import pandas as pd
import pytest

import ecommerce_recsys.retrieval.two_tower as two_tower_module
from ecommerce_recsys.retrieval.base import RetrievalContext
from ecommerce_recsys.retrieval.two_tower import (
    TrainingExample,
    TwoTowerRetriever,
    _sample_negative_indices,
    build_training_examples,
    encode_history,
)


def test_encode_history_uses_latest_occurrence_of_recent_distinct_items():
    mapping = {"A": 0, "B": 1, "C": 2}
    assert encode_history(("A", "B", "A"), mapping, 2) == [1, 0]
    assert encode_history(("A", "B", "A", "C", "unknown"), mapping, 2) == [0, 2]
    with pytest.raises(ValueError, match="positive"):
        encode_history(("A",), mapping, 0)


def test_training_examples_exclude_all_events_at_the_positive_timestamp():
    items = ["A", "B", "C"]
    mapping = {item: index for index, item in enumerate(items)}
    events = pd.DataFrame(
        {
            "user_id": ["u", "u", "u", "v", "v"],
            "item_id": ["A", "B", "C", "B", "C"],
            "timestamp": [1, 2, 2, 1, 2],
        }
    )
    examples, first_seen = build_training_examples(events, frozenset(items), mapping, 3)
    assert examples == [
        TrainingExample((0,), (0,), 1, 2, (1, 2)),
        TrainingExample((0,), (0,), 2, 2, (1, 2)),
        TrainingExample((1,), (1,), 2, 2, (2,)),
    ]
    assert first_seen == {"A": 1, "B": 1, "C": 2}


def test_same_timestamp_sibling_targets_are_never_sampled_as_negatives():
    events = pd.DataFrame(
        {
            "user_id": ["x", "y", "z", "u", "u", "u"],
            "item_id": ["B", "C", "D", "A", "B", "C"],
            "timestamp": [1, 1, 1, 1, 2, 2],
        }
    )
    mapping = {item: index for index, item in enumerate(("A", "B", "C", "D"))}
    examples, first_seen = build_training_examples(events, frozenset(mapping), mapping, 10)
    positive_b = next(example for example in examples if example.positive == mapping["B"])
    assert positive_b.simultaneous_items == (mapping["B"], mapping["C"])

    first_seen_array = np.array([first_seen[item] for item in ("A", "B", "C", "D")], dtype=np.int64)
    eligible_order = np.argsort(first_seen_array, kind="stable")
    negatives = _sample_negative_indices(
        positive_b.timestamp,
        set(positive_b.history) | set(positive_b.simultaneous_items),
        20,
        first_seen_array[eligible_order],
        eligible_order,
        np.random.default_rng(42),
    )
    assert negatives is not None
    assert set(negatives.tolist()) == {mapping["D"]}


def test_negative_sampling_blocks_full_history_beyond_encoder_truncation():
    items = ("A", "B", "C", "X")
    mapping = {item: index for index, item in enumerate(items)}
    events = pd.DataFrame(
        {
            "user_id": ["x", "y", "u", "u", "u"],
            "item_id": ["X", "C", "X", "A", "B"],
            "timestamp": [1, 1, 2, 3, 4],
        }
    )
    examples, first_seen = build_training_examples(events, frozenset(items), mapping, 1)
    target_b = next(example for example in examples if example.positive == mapping["B"])
    assert target_b.history == (mapping["A"],)
    assert set(target_b.blocked_history) == {mapping["X"], mapping["A"]}

    first_seen_array = np.array([first_seen[item] for item in items], dtype=np.int64)
    eligible_order = np.argsort(first_seen_array, kind="stable")
    negatives = _sample_negative_indices(
        target_b.timestamp,
        set(target_b.blocked_history) | set(target_b.simultaneous_items),
        20,
        first_seen_array[eligible_order],
        eligible_order,
        np.random.default_rng(7),
    )
    assert negatives is not None
    assert set(negatives.tolist()) == {mapping["C"]}


def test_training_history_uses_the_latest_occurrence_like_inference():
    events = pd.DataFrame(
        {
            "user_id": ["u", "u", "u", "u"],
            "item_id": ["A", "B", "A", "C"],
            "timestamp": [1, 2, 3, 4],
        }
    )
    mapping = {item: index for index, item in enumerate(("A", "B", "C"))}
    examples, _ = build_training_examples(events, frozenset(mapping), mapping, 2)
    target_c = next(example for example in examples if example.positive == mapping["C"])
    assert list(target_c.history) == encode_history(("A", "B", "A"), mapping, 2) == [1, 0]
    context = RetrievalContext("u", ("A", "B", "A"))
    assert context.history == ("A", "B")
    assert context.ordered_history == ("A", "B", "A")
    assert encode_history(context.ordered_history, mapping, 2) == [1, 0]


def test_fit_skips_examples_without_causal_negatives_instead_of_crashing():
    pytest.importorskip("torch")
    catalog = pd.DataFrame({"item_id": ["A", "B"], "category_id": ["x", "x"]})
    events = pd.DataFrame({"user_id": ["u", "u"], "item_id": ["A", "B"], "timestamp": [1, 2]})
    retriever = TwoTowerRetriever(catalog).fit(
        events, dimension=4, max_history=2, epochs=1, negatives=5, batch_size=8
    )
    assert retriever.generated_examples == 1
    assert retriever.train_examples == 0
    assert retriever.skipped_examples == 1
    assert retriever.skipped_example_rate == 1.0
    assert retriever.generate(RetrievalContext("u", ("A",)), 2) == []


def test_refit_with_no_trainable_examples_clears_previous_model():
    pytest.importorskip("torch")
    catalog = pd.DataFrame({"item_id": ["A", "B", "C"], "category_id": ["x"] * 3})
    trainable = pd.DataFrame(
        {
            "user_id": ["other"] * 3 + ["u", "u"],
            "item_id": ["A", "B", "C", "A", "B"],
            "timestamp": [1, 1, 1, 2, 3],
        }
    )
    untrainable = pd.DataFrame({"user_id": ["u", "u"], "item_id": ["A", "B"], "timestamp": [1, 2]})
    retriever = TwoTowerRetriever(catalog).fit(
        trainable, dimension=4, max_history=2, epochs=1, negatives=1, batch_size=8, seed=42
    )
    assert retriever.generate(RetrievalContext("u", ("A",)), 2)
    retriever.fit(
        untrainable, dimension=4, max_history=2, epochs=1, negatives=1, batch_size=8, seed=42
    )
    assert retriever.model is None
    assert retriever.item_vectors is None
    assert retriever.generate(RetrievalContext("u", ("A",)), 2) == []


def test_fit_handles_negative_sampler_skip_inside_a_batch(monkeypatch):
    pytest.importorskip("torch")
    catalog = pd.DataFrame({"item_id": ["A", "B", "C", "D"], "category_id": ["x"] * 4})
    events = pd.DataFrame(
        {
            "user_id": ["other"] * 4 + ["u"] * 3,
            "item_id": ["A", "B", "C", "D", "A", "B", "C"],
            "timestamp": [1, 1, 1, 1, 2, 3, 4],
        }
    )
    original_sampler = two_tower_module._sample_negative_indices
    calls = 0

    def skip_second_example(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return None
        return original_sampler(*args, **kwargs)

    monkeypatch.setattr(two_tower_module, "_sample_negative_indices", skip_second_example)
    retriever = TwoTowerRetriever(catalog).fit(
        events, dimension=4, max_history=2, epochs=1, negatives=1, batch_size=8, seed=42
    )

    assert retriever.generated_examples == 2
    assert retriever.train_examples == 1
    assert retriever.skipped_examples == 1
    assert retriever.skipped_example_rate == 0.5
    assert retriever.skipped_batch_sampler_attempts == 1
    assert calls == 2
    assert retriever.parameter_bytes > 0
    assert retriever.item_vectors is not None


def test_fit_with_all_batch_samples_skipped_does_not_expose_untrained_model(monkeypatch):
    pytest.importorskip("torch")
    catalog = pd.DataFrame({"item_id": ["A", "B", "C"], "category_id": ["x"] * 3})
    events = pd.DataFrame(
        {
            "user_id": ["other"] * 3 + ["u", "u"],
            "item_id": ["A", "B", "C", "A", "B"],
            "timestamp": [1, 1, 1, 2, 3],
        }
    )
    monkeypatch.setattr(two_tower_module, "_sample_negative_indices", lambda *args: None)
    retriever = TwoTowerRetriever(catalog).fit(
        events, dimension=4, max_history=2, epochs=1, negatives=1, batch_size=8, seed=42
    )
    assert retriever.generated_examples == 1
    assert retriever.train_examples == 0
    assert retriever.skipped_examples == 1
    assert retriever.skipped_batch_sampler_attempts == 1
    assert retriever.generate(RetrievalContext("u", ("A",)), 2) == []


def test_tower_trains_causal_same_timestamp_examples_and_filters_seen():
    pytest.importorskip("torch")
    catalog = pd.DataFrame({"item_id": ["A", "B", "C", "D"], "category_id": ["x", "x", "y", None]})
    events = pd.DataFrame(
        {
            "user_id": ["u", "v", "w", "u", "u", "v"],
            "item_id": ["A", "B", "D", "B", "C", "C"],
            "timestamp": [1, 1, 1, 2, 2, 2],
        }
    )
    retriever = TwoTowerRetriever(catalog).fit(
        events, dimension=4, max_history=2, epochs=1, negatives=1, batch_size=8, seed=42
    )
    assert retriever.train_examples == 3
    context = RetrievalContext("u", ("A", "A"))
    results = retriever.generate(context, 3)
    assert [candidate.item_id for candidate in retriever.generate(context, 2)] == [
        candidate.item_id for candidate in results[:2]
    ]
    assert [(candidate.score, candidate.item_id) for candidate in results] == sorted(
        [(candidate.score, candidate.item_id) for candidate in results],
        key=lambda pair: (-pair[0], pair[1]),
    )
    assert len({candidate.item_id for candidate in results}) == len(results)
    assert "A" not in {candidate.item_id for candidate in results}
    assert all(candidate.evidence[0].source == "two_tower" for candidate in results)
    assert retriever.generate(RetrievalContext(), 3) == []
    retriever.item_vectors[:] = 0.0
    tied = retriever.generate(context, 3)
    assert [candidate.item_id for candidate in tied] == ["B", "C", "D"]


def test_fit_rejects_null_identifiers_before_string_normalization():
    catalog = pd.DataFrame({"item_id": ["A"], "category_id": [None]})
    retriever = TwoTowerRetriever(catalog)
    interactions = pd.DataFrame({"user_id": [None], "item_id": ["A"], "timestamp": [1]})
    with pytest.raises(ValueError, match="non-null"):
        retriever.fit(interactions)
