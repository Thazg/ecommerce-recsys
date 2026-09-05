"""Unit tests for raw and canonical data schemas.

Milestone 1 — Dataset Selection and Data Contract.
"""

import pytest
from pydantic import ValidationError

from ecommerce_recsys.data.schemas import (
    CanonicalInteraction,
    CanonicalItem,
    EventType,
    RawInteraction,
)


def test_valid_raw_interaction():
    raw = RawInteraction(
        timestamp=1433221332117,
        visitorid=257597,
        event=EventType.VIEW,
        itemid=355908,
        transactionid=None,
    )
    assert raw.timestamp == 1433221332117
    assert raw.visitorid == 257597
    assert raw.event == EventType.VIEW
    assert raw.itemid == 355908
    assert raw.transactionid is None


def test_invalid_raw_interaction_timestamp():
    with pytest.raises(ValidationError):
        RawInteraction(
            timestamp=-10,
            visitorid=1,
            event=EventType.VIEW,
            itemid=2,
        )


def test_invalid_raw_interaction_event():
    with pytest.raises(ValidationError):
        RawInteraction(
            timestamp=1433221332117,
            visitorid=1,
            event="unknown_event",
            itemid=2,
        )


def test_canonical_interaction_from_raw():
    raw = RawInteraction(
        timestamp=1433221332117,
        visitorid=12345,
        event=EventType.ADD_TO_CART,
        itemid=67890,
    )
    canonical = CanonicalInteraction.from_raw(raw)

    assert canonical.user_id == "12345"
    assert canonical.item_id == "67890"
    assert canonical.timestamp == 1433221332117
    assert canonical.event_type == "addtocart"
    assert canonical.event_weight is None


def test_canonical_interaction_empty_id():
    with pytest.raises(ValidationError):
        CanonicalInteraction(
            user_id="",
            item_id="67890",
            timestamp=1433221332117,
            event_type="view",
        )


def test_canonical_item_valid():
    item = CanonicalItem(
        item_id="100",
        category_id="electronics",
        price=19.99,
    )
    assert item.item_id == "100"
    assert item.category_id == "electronics"
    assert item.price == 19.99
    assert item.brand is None
