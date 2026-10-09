"""CPU two-tower retriever with causal next-novel-item training examples."""

from __future__ import annotations

from time import perf_counter
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

from ecommerce_recsys.retrieval.base import Candidate, CandidateGenerator, RetrievalContext

TRAIN_LOGIT_SCALE = 20.0


class TrainingExample(NamedTuple):
    """Encoded prefix, full seen set, positive and simultaneous timestamp bucket."""

    history: tuple[int, ...]
    blocked_history: tuple[int, ...]
    positive: int
    timestamp: int
    simultaneous_items: tuple[int, ...]


def encode_history(
    history: tuple[str, ...], item_to_index: dict[str, int], limit: int
) -> list[int]:
    """Keep the latest occurrence of each known item, up to the history limit."""
    if limit <= 0:
        raise ValueError("History length must be positive.")
    recent: list[int] = []
    seen: set[str] = set()
    for item in reversed(history):
        if item in seen or item not in item_to_index:
            continue
        seen.add(item)
        recent.append(item_to_index[item])
        if len(recent) == limit:
            break
    return list(reversed(recent))


def build_training_examples(
    interactions: pd.DataFrame,
    catalog: frozenset[str],
    item_to_index: dict[str, int],
    max_history: int,
) -> tuple[list[TrainingExample], dict[str, int]]:
    """Build first-novel-item targets from user history at strictly earlier timestamps."""
    required = {"user_id", "item_id", "timestamp"}
    if (
        not required.issubset(interactions.columns)
        or interactions[list(required)].isna().any().any()
    ):
        raise ValueError("Training interactions require non-null user, item and timestamp.")
    frame = interactions[["user_id", "item_id", "timestamp"]].copy()
    frame["user_id"] = frame["user_id"].astype(str)
    frame["item_id"] = frame["item_id"].astype(str)
    frame = frame[frame["item_id"].isin(catalog)].sort_values(
        ["user_id", "timestamp", "item_id"], kind="mergesort"
    )
    first_seen = frame.groupby("item_id", sort=False)["timestamp"].min().to_dict()
    examples: list[TrainingExample] = []
    for _, user_events in frame.groupby("user_id", sort=False):
        history: list[str] = []
        seen: set[str] = set()
        records = user_events[["item_id", "timestamp"]].to_numpy()
        position = 0
        while position < len(records):
            timestamp = int(records[position, 1])
            end = position + 1
            while end < len(records) and records[end, 1] == timestamp:
                end += 1
            bucket_items = list(dict.fromkeys(str(item) for item in records[position:end, 0]))
            new_items = [item for item in bucket_items if item not in seen]
            encoded = encode_history(tuple(history), item_to_index, max_history)
            if encoded:
                blocked_history = tuple(sorted(item_to_index[item] for item in seen))
                simultaneous = tuple(item_to_index[item] for item in bucket_items)
                examples.extend(
                    TrainingExample(
                        tuple(encoded),
                        blocked_history,
                        item_to_index[item],
                        timestamp,
                        simultaneous,
                    )
                    for item in new_items
                )
            history.extend(str(item) for item in records[position:end, 0])
            seen.update(bucket_items)
            position = end
    return examples, first_seen


def _has_causal_negative(
    timestamp: int,
    blocked: set[int],
    first_seen_sorted: np.ndarray,
    eligible_order: np.ndarray,
) -> bool:
    """Check causal negative availability without scanning common large pools."""
    eligible_count = int(np.searchsorted(first_seen_sorted, timestamp, side="left"))
    if eligible_count > len(blocked):
        return True
    return any(int(index) not in blocked for index in eligible_order[:eligible_count])


def _sample_negative_indices(
    timestamp: int,
    blocked: set[int],
    count: int,
    first_seen_sorted: np.ndarray,
    eligible_order: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray | None:
    """Draw uniform causal negatives, or return None when none are available."""
    eligible_count = int(np.searchsorted(first_seen_sorted, timestamp, side="left"))
    if eligible_count == 0:
        return None
    if not _has_causal_negative(timestamp, blocked, first_seen_sorted, eligible_order):
        return None
    sampled: list[int] = []
    attempts = 0
    while len(sampled) < count and attempts < count * 100:
        candidate = int(eligible_order[rng.integers(0, eligible_count)])
        attempts += 1
        if candidate not in blocked:
            sampled.append(candidate)
    if len(sampled) < count:
        eligible = [
            int(index) for index in eligible_order[:eligible_count] if int(index) not in blocked
        ]
        if not eligible:
            return None
        sampled.extend(rng.choice(eligible, count - len(sampled), replace=True).tolist())
    return np.asarray(sampled, dtype=np.int64)


class TwoTowerRetriever(CandidateGenerator):
    """An exact-scoring, train-time-catalog two-tower candidate source."""

    name = "two_tower"

    def __init__(self, catalog: pd.DataFrame) -> None:
        if not {"item_id", "category_id"}.issubset(catalog.columns):
            raise ValueError("Catalog requires item_id and category_id.")
        if catalog[["item_id"]].isna().any().any():
            raise ValueError("Catalog item IDs must not be null.")
        self.catalog_frame = catalog[["item_id", "category_id"]].copy()
        self.catalog_frame["item_id"] = self.catalog_frame["item_id"].astype(str)
        self.catalog_frame["category_id"] = (
            self.catalog_frame["category_id"].fillna("__unknown__").astype(str)
        )
        self.catalog_frame = self.catalog_frame.drop_duplicates("item_id").sort_values("item_id")
        super().__init__(self.catalog_frame["item_id"])
        self.item_ids = self.catalog_frame["item_id"].tolist()
        self.item_to_index = {item: index for index, item in enumerate(self.item_ids)}
        categories = sorted(set(self.catalog_frame["category_id"]) - {"__unknown__"})
        self.category_to_index = {"__unknown__": 0, **{c: i + 1 for i, c in enumerate(categories)}}
        self.category_indices = np.array(
            [self.category_to_index[value] for value in self.catalog_frame["category_id"]],
            dtype=np.int64,
        )
        self.model: Any = None
        self.item_vectors: np.ndarray | None = None
        self.max_history = 0
        self.dimension = 0
        self.fit_seconds = 0.0
        self.training_seconds = 0.0
        self.parameter_bytes = 0
        self.item_vector_bytes = 0
        self.train_examples = 0
        self.generated_examples = 0
        self.skipped_examples = 0
        self.skipped_example_rate = 0.0
        self.skipped_batch_sampler_attempts = 0

    def fit(
        self,
        interactions: pd.DataFrame,
        *,
        max_history: int = 20,
        dimension: int = 64,
        epochs: int = 3,
        negatives: int = 5,
        batch_size: int = 1024,
        seed: int = 42,
    ) -> "TwoTowerRetriever":
        required = {"user_id", "item_id", "timestamp"}
        if (
            not required.issubset(interactions.columns)
            or interactions[list(required)].isna().any().any()
        ):
            raise ValueError("Training interactions require non-null user, item and timestamp.")
        if min(max_history, dimension, epochs, negatives, batch_size) <= 0:
            raise ValueError("Model dimensions, epochs, negatives and batch size must be positive.")
        # A retriever can be refit. Clear any previous fitted state before an
        # early return so an untrainable new dataset cannot expose stale scores.
        self.model = None
        self.item_vectors = None
        self.max_history = max_history
        self.dimension = dimension
        self.fit_seconds = 0.0
        self.training_seconds = 0.0
        self.parameter_bytes = 0
        self.item_vector_bytes = 0
        self.train_examples = 0
        self.generated_examples = 0
        self.skipped_examples = 0
        self.skipped_example_rate = 0.0
        self.skipped_batch_sampler_attempts = 0
        fit_started = perf_counter()
        import torch
        from torch import nn

        torch.manual_seed(seed)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        examples, first_seen = build_training_examples(
            interactions, self.catalog, self.item_to_index, max_history
        )
        self.generated_examples = len(examples)
        first_seen_array = np.full(len(self.item_ids), np.iinfo(np.int64).max, dtype=np.int64)
        for item, timestamp in first_seen.items():
            first_seen_array[self.item_to_index[item]] = int(timestamp)
        eligible_order = np.argsort(first_seen_array, kind="stable")
        sorted_first_seen = first_seen_array[eligible_order]
        trainable_examples = []
        for example in examples:
            blocked = set(example.blocked_history)
            blocked.update(example.simultaneous_items)
            if _has_causal_negative(example.timestamp, blocked, sorted_first_seen, eligible_order):
                trainable_examples.append(example)
        if not trainable_examples:
            self.skipped_examples = self.generated_examples
            self.skipped_example_rate = 1.0 if self.generated_examples else 0.0
            self.fit_seconds = perf_counter() - fit_started
            return self

        class Network(nn.Module):
            def __init__(network_self) -> None:
                super().__init__()
                network_self.item = nn.Embedding(len(self.item_ids), dimension, sparse=True)
                network_self.category = nn.Embedding(
                    len(self.category_to_index), dimension, sparse=True
                )
                network_self.register_buffer(
                    "item_categories", torch.as_tensor(self.category_indices, dtype=torch.long)
                )
                network_self.user_projection = nn.Sequential(
                    nn.Linear(dimension, dimension), nn.ReLU(), nn.Linear(dimension, dimension)
                )
                network_self.item_projection = nn.Sequential(
                    nn.Linear(dimension * 2, dimension), nn.ReLU(), nn.Linear(dimension, dimension)
                )

            def encode_user(network_self, histories_tensor):
                mask = histories_tensor.ne(-1)
                embedded = network_self.item(histories_tensor.clamp_min(0))
                pooled = (embedded * mask.unsqueeze(-1)).sum(1) / mask.sum(
                    1, keepdim=True
                ).clamp_min(1)
                return nn.functional.normalize(network_self.user_projection(pooled), dim=-1)

            def encode_item(network_self, item_tensor):
                cats = network_self.item_categories[item_tensor]
                joined = torch.cat(
                    (network_self.item(item_tensor), network_self.category(cats)), dim=-1
                )
                return nn.functional.normalize(network_self.item_projection(joined), dim=-1)

        self.model = Network()
        sparse_parameters = [self.model.item.weight, self.model.category.weight]
        dense_parameters = [
            parameter
            for name, parameter in self.model.named_parameters()
            if name not in {"item.weight", "category.weight"}
        ]
        dense_optimizer = torch.optim.Adam(dense_parameters, lr=0.003)
        sparse_optimizer = torch.optim.SparseAdam(sparse_parameters, lr=0.003)
        rng = np.random.default_rng(seed)
        order = np.arange(len(trainable_examples))
        trained_example_indices: set[int] = set()
        started = perf_counter()
        self.model.train()
        for _ in range(epochs):
            rng.shuffle(order)
            for start in range(0, len(order), batch_size):
                selected_indices = order[start : start + batch_size]
                history_rows = []
                positive_rows = []
                negative_rows = []
                sampled_indices = []
                for index in selected_indices:
                    example = trainable_examples[index]
                    blocked = set(example.blocked_history)
                    blocked.update(example.simultaneous_items)
                    negative_indices = _sample_negative_indices(
                        example.timestamp,
                        blocked,
                        negatives,
                        sorted_first_seen,
                        eligible_order,
                        rng,
                    )
                    if negative_indices is None:
                        self.skipped_batch_sampler_attempts += 1
                        continue
                    padded_history = np.full(max_history, -1, dtype=np.int64)
                    padded_history[-len(example.history) :] = example.history[-max_history:]
                    history_rows.append(padded_history)
                    positive_rows.append(example.positive)
                    negative_rows.append(negative_indices)
                    sampled_indices.append(int(index))
                if not history_rows:
                    continue
                batch_users = np.stack(history_rows)
                positives = np.asarray(positive_rows, dtype=np.int64)
                negatives_array = np.stack(negative_rows)
                users_tensor = torch.as_tensor(batch_users, dtype=torch.long)
                positives_tensor = torch.as_tensor(positives, dtype=torch.long)
                negative_tensor = torch.as_tensor(negatives_array, dtype=torch.long)
                user_vectors = self.model.encode_user(users_tensor)
                candidate_ids = torch.cat((positives_tensor[:, None], negative_tensor), dim=1)
                candidate_vectors = self.model.encode_item(candidate_ids.reshape(-1)).reshape(
                    len(history_rows), negatives + 1, dimension
                )
                logits = (
                    torch.einsum("bd,bkd->bk", user_vectors, candidate_vectors) * TRAIN_LOGIT_SCALE
                )
                loss = nn.functional.cross_entropy(
                    logits, torch.zeros(len(history_rows), dtype=torch.long)
                )
                dense_optimizer.zero_grad(set_to_none=True)
                sparse_optimizer.zero_grad(set_to_none=True)
                loss.backward()
                dense_optimizer.step()
                sparse_optimizer.step()
                trained_example_indices.update(sampled_indices)
        self.training_seconds = perf_counter() - started
        self.train_examples = len(trained_example_indices)
        self.skipped_examples = self.generated_examples - self.train_examples
        self.skipped_example_rate = (
            self.skipped_examples / self.generated_examples if self.generated_examples else 0.0
        )
        if not trained_example_indices:
            self.model = None
            self.fit_seconds = perf_counter() - fit_started
            return self
        self.model.eval()
        with torch.no_grad():
            item_vectors = self.model.encode_item(torch.arange(len(self.item_ids))).cpu().numpy()
        self.item_vectors = item_vectors.astype(np.float32, copy=False)
        self.parameter_bytes = sum(
            parameter.numel() * parameter.element_size() for parameter in self.model.parameters()
        )
        self.item_vector_bytes = self.item_vectors.nbytes
        self.fit_seconds = perf_counter() - fit_started
        return self

    def generate(self, context: RetrievalContext, limit: int) -> list[Candidate]:
        from ecommerce_recsys.retrieval.base import validate_limit

        validate_limit(limit)
        if self.model is None or self.item_vectors is None or not context.ordered_history:
            return []
        history = encode_history(context.ordered_history, self.item_to_index, self.max_history)
        if not history:
            return []
        import torch

        with torch.no_grad():
            ids = torch.full((1, self.max_history), -1, dtype=torch.long)
            ids[0, -len(history) :] = torch.tensor(history)
            vector = self.model.encode_user(ids).cpu().numpy()[0]
        scores = self.item_vectors @ vector
        if not np.isfinite(scores).all():
            raise ValueError("Two-tower model produced nonfinite candidate scores.")
        eligible = np.ones(len(self.item_ids), dtype=bool)
        for item in context.history:
            index = self.item_to_index.get(item)
            if index is not None:
                eligible[index] = False
        indices = np.flatnonzero(eligible)
        count = min(limit, len(indices))
        if not count:
            return []
        threshold = np.partition(scores[indices], -count)[-count]
        above = indices[scores[indices] > threshold]
        ties = indices[scores[indices] == threshold]
        chosen = np.concatenate((above, ties[: count - len(above)]))
        chosen = chosen[np.lexsort((chosen, -scores[chosen]))]
        ranked = [(self.item_ids[index], float(scores[index])) for index in chosen]
        return self._candidates(ranked, context, limit)
