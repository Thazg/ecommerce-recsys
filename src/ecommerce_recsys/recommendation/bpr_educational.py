from __future__ import annotations

import numpy as np
import pandas as pd


class EducationalBPR:
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

    def _build_mappings(
        self,
        interactions: pd.DataFrame,
    ) -> None:
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

    def _sample_training_triplets(
        self,
        interactions: pd.DataFrame,
        negative_samples: int = 1,
    ) -> pd.DataFrame:
        if negative_samples <= 0:
            raise ValueError("negative_samples must be positive")

        all_items = list(self._item_to_index.keys())

        observed_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

        triplets = []

        rng = np.random.default_rng(self.random_state)

        for row in interactions.itertuples(index=False):
            user_id = row.user_id
            positive_item_id = row.item_id

            observed_items = observed_by_user[user_id]
            unobserved_items = [item_id for item_id in all_items if item_id not in observed_items]

            if len(unobserved_items) < negative_samples:
                raise ValueError(f"Not enough unobserved items for user {user_id}")

            sampled_negatives = rng.choice(
                unobserved_items,
                size=negative_samples,
                replace=False,
            )

            for negative_item_id in sampled_negatives:
                triplets.append(
                    {
                        "user_id": user_id,
                        "positive_item_id": positive_item_id,
                        "negative_item_id": negative_item_id,
                    }
                )

        return pd.DataFrame(triplets)

    def fit(self, interactions: pd.DataFrame) -> "EducationalBPR":
        required_columns = {"user_id", "item_id"}

        if not required_columns.issubset(interactions.columns):
            missing = required_columns - set(interactions.columns)
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        if interactions.empty:
            raise ValueError("interactions must not be empty")

        self._build_mappings(interactions)

        self._seen_items_by_user = interactions.groupby("user_id")["item_id"].apply(set).to_dict()

        self._initialize_factors(
            n_users=len(self._user_to_index),
            n_items=len(self._item_to_index),
        )

        for _ in range(self.epochs):
            triplets = self._sample_training_triplets(
                interactions,
                negative_samples=1,
            )

            for row in triplets.itertuples(index=False):
                self._update_factors(
                    user_id=row.user_id,
                    positive_item_id=row.positive_item_id,
                    negative_item_id=row.negative_item_id,
                )

        self._fitted = True

        return self

    def _update_factors(
        self,
        user_id: object,
        positive_item_id: object,
        negative_item_id: object,
    ) -> None:
        user_index = self._user_to_index[user_id]
        positive_index = self._item_to_index[positive_item_id]
        negative_index = self._item_to_index[negative_item_id]

        user_vector = self._user_factors[user_index]
        positive_vector = self._item_factors[positive_index]
        negative_vector = self._item_factors[negative_index]

        score_difference = np.dot(
            user_vector,
            positive_vector - negative_vector,
        )

        sigmoid_negative = 1.0 / (1.0 + np.exp(score_difference))

        user_gradient = (
            -sigmoid_negative * (positive_vector - negative_vector)
            + 2.0 * self.regularization * user_vector
        )

        positive_gradient = (
            -sigmoid_negative * user_vector + 2.0 * self.regularization * positive_vector
        )

        negative_gradient = (
            sigmoid_negative * user_vector + 2.0 * self.regularization * negative_vector
        )

        self._user_factors[user_index] -= self.learning_rate * user_gradient

        self._item_factors[positive_index] -= self.learning_rate * positive_gradient

        self._item_factors[negative_index] -= self.learning_rate * negative_gradient

    def _compute_loss(
        self,
        triplets: pd.DataFrame,
    ) -> float:
        total_loss = 0.0

        for row in triplets.itertuples(index=False):
            user_index = self._user_to_index[row.user_id]
            positive_index = self._item_to_index[row.positive_item_id]
            negative_index = self._item_to_index[row.negative_item_id]

            user_vector = self._user_factors[user_index]
            positive_vector = self._item_factors[positive_index]
            negative_vector = self._item_factors[negative_index]

            score_difference = np.dot(
                user_vector,
                positive_vector - negative_vector,
            )

            pairwise_loss = np.logaddexp(0.0, -score_difference)

            regularization_loss = self.regularization * (
                np.sum(user_vector**2) + np.sum(positive_vector**2) + np.sum(negative_vector**2)
            )

            total_loss += pairwise_loss + regularization_loss

        if len(triplets) == 0:
            return 0.0

        return float(total_loss / len(triplets))

    def predict(
        self,
        user_id: object,
        item_id: object,
    ) -> float:
        if not self._fitted:
            raise RuntimeError("Model has not been fitted")

        if user_id not in self._user_to_index:
            raise ValueError(f"Unknown user_id: {user_id}")

        if item_id not in self._item_to_index:
            raise ValueError(f"Unknown item_id: {item_id}")

        user_index = self._user_to_index[user_id]
        item_index = self._item_to_index[item_id]

        user_vector = self._user_factors[user_index]
        item_vector = self._item_factors[item_index]

        return float(np.dot(user_vector, item_vector))

    def recommend(
        self,
        user_id: object,
        k: int,
    ) -> list[object]:
        if not self._fitted:
            raise RuntimeError("Model has not been fitted")

        if k <= 0:
            raise ValueError("k must be positive")

        if user_id not in self._user_to_index:
            raise ValueError(f"Unknown user_id: {user_id}")

        user_index = self._user_to_index[user_id]

        user_vector = self._user_factors[user_index]

        scores = self._item_factors @ user_vector

        seen_items = set(self._seen_items_by_user.get(user_id, set()))

        ranked_indices = np.argsort(-scores)

        recommendations = []

        for item_index in ranked_indices:
            item_id = self._index_to_item[item_index]

            if item_id in seen_items:
                continue

            recommendations.append(item_id)

            if len(recommendations) == k:
                break

        return recommendations
