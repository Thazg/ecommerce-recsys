"""Educational model outputs require a completely successful latest fit."""

import numpy as np
import pandas as pd
import pytest

from ecommerce_recsys.recommendation.bpr_educational import EducationalBPR
from ecommerce_recsys.recommendation.matrix_factorization_educational import (
    EducationalMatrixFactorization,
)


@pytest.fixture(params=[EducationalMatrixFactorization, EducationalBPR], ids=["mf", "bpr"])
def model_type(request):
    return request.param


@pytest.fixture
def valid_interactions():
    return pd.DataFrame({"user_id": ["u", "v", "w"], "item_id": ["a", "b", "c"]})


def _assert_unavailable(model):
    assert model._fitted is False
    with pytest.raises(RuntimeError, match="not been fitted"):
        model.predict("v", "b")
    with pytest.raises(RuntimeError, match="not been fitted"):
        model.recommend("v", 1)


def test_failed_initial_fit_does_not_expose_random_factors(model_type):
    model = model_type(factors=2, epochs=1)
    saturated = pd.DataFrame({"user_id": ["u", "u", "v"], "item_id": ["a", "b", "a"]})

    with pytest.raises(ValueError, match="Not enough unobserved"):
        model.fit(saturated)

    _assert_unavailable(model)


@pytest.mark.parametrize(
    "failure", ["sampling", "missing_column", "empty", "null_user", "null_item", "training"]
)
def test_failed_refit_disables_outputs_and_successful_refit_recovers(
    model_type, valid_interactions, failure, monkeypatch
):
    model = model_type(factors=2, epochs=1)
    model.fit(valid_interactions)
    assert np.isfinite(model.predict("v", "b"))
    invalid = valid_interactions.copy()
    error_type = ValueError
    if failure == "sampling":
        invalid = pd.DataFrame({"user_id": ["u", "u", "v"], "item_id": ["a", "b", "a"]})
    elif failure == "missing_column":
        invalid = invalid.drop(columns="item_id")
        error_type = (ValueError, KeyError)
    elif failure == "empty":
        invalid = invalid.iloc[:0]
    elif failure.startswith("null_"):
        invalid.loc[0, "user_id" if failure == "null_user" else "item_id"] = None

    with monkeypatch.context() as patch:
        if failure == "training":
            original_update = model._update_factors

            def fail_after_update(*args, **kwargs):
                original_update(*args, **kwargs)
                raise ValueError("injected training failure")

            patch.setattr(model, "_update_factors", fail_after_update)
        with pytest.raises(error_type):
            model.fit(invalid)

    _assert_unavailable(model)
    assert model.fit(valid_interactions) is model
    reference = model_type(factors=2, epochs=1).fit(valid_interactions)
    assert model.predict("v", "b") == reference.predict("v", "b")
    assert model.recommend("v", 2) == reference.recommend("v", 2)
