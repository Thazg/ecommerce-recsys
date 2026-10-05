import pandas as pd
import pytest

from ecommerce_recsys.data.catalog import build_train_catalog


def test_catalog_uses_only_training_items_and_past_category_snapshots(tmp_path):
    train = pd.DataFrame({"item_id": ["A", "B"], "timestamp": [10, 10]})
    pd.DataFrame(
        [
            (5, "A", "categoryid", "old"),
            (11, "A", "categoryid", "future"),
            (5, "C", "categoryid", "not_in_train"),
        ],
        columns=["timestamp", "itemid", "property", "value"],
    ).to_csv(tmp_path / "item_properties_part1.csv", index=False)
    pd.DataFrame(
        [(9, "A", "categoryid", "current"), (11, "B", "categoryid", "future")],
        columns=["timestamp", "itemid", "property", "value"],
    ).to_csv(tmp_path / "item_properties_part2.csv", index=False)

    catalog = build_train_catalog(train, tmp_path).set_index("item_id")

    assert set(catalog.index) == {"A", "B"}
    assert catalog.loc["A", "category_id"] == "current"
    assert pd.isna(catalog.loc["B", "category_id"])


def test_catalog_rejects_conflicting_category_tie(tmp_path):
    train = pd.DataFrame({"item_id": ["A"], "timestamp": [10]})
    pd.DataFrame(
        [(5, "A", "categoryid", "first")],
        columns=["timestamp", "itemid", "property", "value"],
    ).to_csv(tmp_path / "item_properties_part1.csv", index=False)
    pd.DataFrame(
        [(5, "A", "categoryid", "second")],
        columns=["timestamp", "itemid", "property", "value"],
    ).to_csv(tmp_path / "item_properties_part2.csv", index=False)

    with pytest.raises(ValueError, match="Conflicting category values"):
        build_train_catalog(train, tmp_path)
