"""Data schemas for raw events and canonical recommendation interactions.

Milestone 1 — Dataset Selection and Data Contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    """Supported interaction event types in the behavioral funnel."""

    VIEW = "view"
    ADD_TO_CART = "addtocart"
    TRANSACTION = "transaction"


class RawInteraction(BaseModel):
    """Raw interaction schema representing a row from Retailrocket events.csv."""

    model_config = ConfigDict(frozen=True)

    timestamp: int = Field(
        ...,
        description="Unix epoch timestamp in milliseconds",
    )
    visitorid: int = Field(
        ...,
        description="Unique visitor identifier",
    )
    event: EventType = Field(
        ...,
        description="Interaction event type",
    )
    itemid: int = Field(
        ...,
        description="Unique catalog item identifier",
    )
    transactionid: int | None = Field(
        default=None,
        description="Transaction ID (only present for transaction events)",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Timestamp must be a positive integer.")
        return v

    @field_validator("visitorid", "itemid")
    @classmethod
    def validate_positive_ids(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Identifier must be non-negative.")
        return v


class CanonicalInteraction(BaseModel):
    """Canonical interaction schema adhering to the logical Data Contract."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(
        ...,
        min_length=1,
        description="Persistent user/visitor identifier",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Catalog item identifier",
    )
    timestamp: int = Field(
        ...,
        gt=0,
        description="Monotonically comparable Unix timestamp in milliseconds",
    )
    event_type: str = Field(
        ...,
        min_length=1,
        description="Funnel event type: view, addtocart, or transaction",
    )
    event_weight: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional weight (unresolved until Milestone 2)",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session grouping identifier",
    )

    @classmethod
    def from_raw(
        cls,
        raw: RawInteraction,
        event_weight: float | None = None,
    ) -> Self:
        """Convert a raw Retailrocket interaction into canonical form."""
        return cls(
            user_id=str(raw.visitorid),
            item_id=str(raw.itemid),
            timestamp=raw.timestamp,
            event_type=raw.event.value,
            event_weight=event_weight,
        )


class CanonicalItem(BaseModel):
    """Canonical item catalog schema."""

    model_config = ConfigDict(frozen=True)

    item_id: str = Field(..., min_length=1, description="Catalog item identifier")
    category_id: str | None = Field(default=None, description="Category identifier")
    brand: str | None = Field(default=None, description="Item brand name or ID")
    price: float | None = Field(default=None, ge=0.0, description="Item price")
    title: str | None = Field(default=None, description="Item title or description")
