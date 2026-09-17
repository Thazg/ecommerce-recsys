from __future__ import annotations

import numpy as np
import pandas as pd


class EducationalMatrixFactorization:
    """Small, readable MF implementation for learning and experimentation."""

    def __init__(
        self,
        factors: int = 8,
        learning_rate: float = 0.01,
        regularization: float = 0.01,
        epochs: int = 20,
        random_state: int = 42,
    ) -> None:
        if factors <= 0:
            raise ValueError("factors must be positive")
        if learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if regularization < 0:
            raise ValueError("regularization must be non-negative")
        if epochs <= 0:
            raise ValueError("epochs must be positive")

        self.factors = factors
        self.learning_rate = learning_rate
        self.regularization = regularization
        self.epochs = epochs
        self.random_state = random_state

        self._user_to_index: dict[object, int] = {}
        self._item_to_index: dict[object, int] = {}
        self._index_to_user: list[object] = []
        self._index_to_item: list[object] = []

        self._user_factors: np.ndarray | None = None
        self._item_factors: np.ndarray | None = None

        self._fitted = False

        self._seen_items_by_user: dict[object, set[object]] = {}

    def _build_mappings(self, interactions: pd.DataFrame) -> None:
        users = sorted(interactions["user_id"].unique())
        items = sorted(interactions["item_id"].unique())

        self._index_to_user = list(users)
        self._index_to_item = list(items)

        self._user_to_index = {user_id: index for index, user_id in enumerate(users)}
        self._item_to_index = {item_id: index for index, item_id in enumerate(items)}

    def _initialize_factors(
        self,
        n_users: int,
        n_items: int,
    ) -> None:
        rng = np.random.default_rng(self.random_state)

        scale = 0.01

        self._user_factors = rng.normal(
            loc=0.0,
            scale=scale,
            size=(n_users, self.factors),
        )

        self._item_factors = rng.normal(
            loc=0.0,
            scale=scale,
            size=(n_items, self.factors),
        )

    def _sample_training_examples(
        self,
        interactions: pd.DataFrame,
        negative_samples: int = 1,
    ) -> pd.DataFrame:
        if negative_samples <= 0:
            raise ValueError("negative_samples must be positive")

        rng = np.random.default_rng(self.random_state)

        all_items = list(self._item_to_index)

        observed_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

        examples: list[tuple[object, object, float]] = []

        for _, row in interactions.iterrows():
            user_id = row["user_id"]
            item_id = row["item_id"]

            examples.append((user_id, item_id, 1.0))

            observed_items = observed_by_user[user_id]
            candidates = [candidate for candidate in all_items if candidate not in observed_items]

            if len(candidates) < negative_samples:
                raise ValueError(f"Not enough unobserved items for user {user_id}")

            sampled_items = rng.choice(
                candidates,
                size=negative_samples,
                replace=False,
            )

            for sampled_item in sampled_items:
                examples.append((user_id, sampled_item, 0.0))

        return pd.DataFrame(
            examples,
            columns=["user_id", "item_id", "label"],
        )

    def fit(self, interactions: pd.DataFrame) -> "EducationalMatrixFactorization":
        required_columns = {"user_id", "item_id"}

        if not required_columns.issubset(interactions.columns):
            missing_columns = required_columns - set(interactions.columns)
            raise KeyError(f"Missing required columns: {sorted(missing_columns)}")

        if interactions.empty:
            raise ValueError("Interactions must not be empty.")

        self._build_mappings(interactions)

        self._seen_items_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

        self._initialize_factors(
            n_users=len(self._index_to_user),
            n_items=len(self._index_to_item),
        )

        training_examples = self._sample_training_examples(
            interactions,
            negative_samples=1,
        )

        for _ in range(self.epochs):
            for _, row in training_examples.iterrows():
                user_index = self._user_to_index[row["user_id"]]
                item_index = self._item_to_index[row["item_id"]]

                self._update_factors(
                    user_index=user_index,
                    item_index=item_index,
                    target=float(row["label"]),
                )

        self._fitted = True

        return self

    def _update_factors(
        self,
        user_index: int,
        item_index: int,
        target: float,
    ) -> None:
        if self._user_factors is None or self._item_factors is None:
            raise RuntimeError("Model has not been fitted.")

        user_factors = self._user_factors[user_index]
        item_factors = self._item_factors[item_index]

        prediction = float(np.dot(user_factors, item_factors))
        error = target - prediction

        user_update = error * item_factors - self.regularization * user_factors
        item_update = error * user_factors - self.regularization * item_factors

        self._user_factors[user_index] = user_factors + self.learning_rate * user_update
        self._item_factors[item_index] = item_factors + self.learning_rate * item_update

    def _compute_loss(self, interactions: pd.DataFrame) -> float:
        if self._user_factors is None or self._item_factors is None:
            raise RuntimeError("Model has not been fitted.")

        training_examples = self._sample_training_examples(
            interactions,
            negative_samples=1,
        )

        squared_error = 0.0

        for _, row in training_examples.iterrows():
            user_index = self._user_to_index[row["user_id"]]
            item_index = self._item_to_index[row["item_id"]]

            prediction = float(
                np.dot(
                    self._user_factors[user_index],
                    self._item_factors[item_index],
                )
            )

            error = float(row["label"]) - prediction
            squared_error += error**2

        mean_squared_error = squared_error / len(training_examples)

        regularization_loss = self.regularization * (
            np.sum(self._user_factors**2) + np.sum(self._item_factors**2)
        )

        return float(mean_squared_error + regularization_loss)

    def predict(self, user_id: object, item_id: object) -> float:
        if self._user_factors is None or self._item_factors is None:
            raise RuntimeError("Model has not been fitted.")

        if user_id not in self._user_to_index:
            raise ValueError(f"Unknown user_id: {user_id}")

        if item_id not in self._item_to_index:
            raise ValueError(f"Unknown item_id: {item_id}")

        user_index = self._user_to_index[user_id]
        item_index = self._item_to_index[item_id]

        return float(
            np.dot(
                self._user_factors[user_index],
                self._item_factors[item_index],
            )
        )

    def recommend(self, user_id: object, k: int) -> list[object]:
        if self._user_factors is None or self._item_factors is None:
            raise RuntimeError("Model has not been fitted.")

        if k <= 0:
            raise ValueError("k must be positive")

        if user_id not in self._user_to_index:
            raise ValueError(f"Unknown user_id: {user_id}")

        user_index = self._user_to_index[user_id]
        user_factors = self._user_factors[user_index]

        scores = self._item_factors @ user_factors

        seen_items = self._seen_items_by_user.get(user_id, set())

        candidates = [
            (item_id, score)
            for item_id, score in zip(self._index_to_item, scores)
            if item_id not in seen_items
        ]

        candidates.sort(key=lambda pair: pair[1], reverse=True)

        return [item_id for item_id, _ in candidates[:k]]
