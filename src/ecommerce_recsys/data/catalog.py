"""Construct a training-time item catalog from historical property snapshots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_train_catalog(train: pd.DataFrame, raw_dir: Path) -> pd.DataFrame:
    """Build the known catalog and latest category snapshot at the train cutoff."""
    property_paths = [raw_dir / f"item_properties_part{part}.csv" for part in (1, 2)]
    missing = [str(path) for path in property_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Raw item properties required for as-of catalog: {missing}")

    item_ids = set(train["item_id"].astype(str))
    categories: dict[str, tuple[int, str]] = {}
    cutoff = train["timestamp"].max()
    for path in property_paths:
        for chunk in pd.read_csv(
            path,
            usecols=["timestamp", "itemid", "property", "value"],
            dtype={"itemid": str, "property": str, "value": str},
            chunksize=500_000,
        ):
            current = chunk.loc[
                (chunk["property"] == "categoryid")
                & (chunk["timestamp"] <= cutoff)
                & chunk["itemid"].isin(item_ids)
                & chunk["value"].notna()
            ]
            for row in current.itertuples(index=False):
                previous = categories.get(row.itemid)
                if (
                    previous is not None
                    and row.timestamp == previous[0]
                    and row.value != previous[1]
                ):
                    raise ValueError(
                        f"Conflicting category values at the same timestamp for item {row.itemid}."
                    )
                if previous is None or row.timestamp >= previous[0]:
                    categories[row.itemid] = (row.timestamp, row.value)

    catalog = pd.DataFrame({"item_id": sorted(item_ids)})
    catalog["category_id"] = catalog["item_id"].map(
        {item_id: value for item_id, (_, value) in categories.items()}
    )
    return catalog
