"""Explicit HTTP inputs, outputs and operator-controlled snapshot configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ecommerce_recsys.serving.cache import validate_cache_settings

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Version = Annotated[str, StringConstraints(min_length=1, max_length=80)]
OutputLimit = Annotated[int, Field(ge=1, le=20)]
Count = Annotated[int, Field(ge=0)]
Route = Literal["hybrid_learned", "recent_popularity"]


def valid_identifier(value: str) -> str:
    if not value.strip() or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("IDs must be nonblank and contain no control characters.")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class RecommendationRequest(StrictModel):
    user_id: Identifier | None = None
    k: OutputLimit = 20

    @field_validator("user_id")
    @classmethod
    def check_user(cls, value):
        return valid_identifier(value) if value is not None else None


class ModelIdentity(StrictModel):
    bundle_version: Version
    cutoff: Annotated[int, Field(gt=0)]


class RecommendationResponse(ModelIdentity):
    request_id: str
    items: Annotated[list[Identifier], Field(max_length=20)]
    route: Route

    @field_validator("items")
    @classmethod
    def check_items(cls, values):
        for value in values:
            valid_identifier(value)
        if len(set(values)) != len(values):
            raise ValueError("Recommendation IDs must be unique.")
        return values


class HealthResponse(StrictModel):
    request_id: str
    status: Literal["alive", "ready", "not_ready"]
    state: Literal["starting", "ready", "failed", "stopped"]
    bundle_version: Version | None = None
    cutoff: Annotated[int, Field(gt=0)] | None = None
    cache: CacheHealth | None = None
    busy_policy: Literal["reject", "recent_popularity"] | None = None
    primary_calls: Annotated[int, Field(ge=0)] | None = None
    fallback_calls: Annotated[int, Field(ge=0)] | None = None


class CacheHealth(StrictModel):
    enabled: bool
    entries: Count
    charged_bytes: Count
    max_entries: Count
    max_bytes: Annotated[int, Field(gt=0)]
    ttl_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    hits: Count
    misses: Count
    evictions: Count
    expirations: Count
    oversized: Count
    failures: Count

    @model_validator(mode="after")
    def check_bounds(self):
        if self.entries > self.max_entries or self.charged_bytes > self.max_bytes:
            raise ValueError("Cache state exceeds its declared bounds.")
        return self


class ServedRecommendationResponse(RecommendationResponse):
    route: Literal["hybrid_learned", "recent_popularity", "recent_popularity_fallback"]
    manifest_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    cache_status: Literal["disabled", "miss", "hit", "bypass"]
    degraded: bool
    degraded_reason: Literal["busy"] | None = None

    @model_validator(mode="after")
    def check_delivery(self):
        if self.degraded:
            if (
                self.route != "recent_popularity_fallback"
                or self.degraded_reason != "busy"
                or self.cache_status != "bypass"
            ):
                raise ValueError("Degraded results require explicit fallback attribution.")
        elif self.degraded_reason is not None or self.route == "recent_popularity_fallback":
            raise ValueError("Primary results cannot claim fallback attribution.")
        return self


class ErrorDetail(StrictModel):
    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    request_id: str
    error: ErrorDetail


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    bundle_path: Path
    manifest_sha256: str
    cache_max_entries: int = 0
    cache_max_bytes: int = 1048576
    cache_ttl_seconds: float = 300.0
    busy_policy: str = "reject"

    def __post_init__(self):
        if not isinstance(self.bundle_path, Path):
            raise ValueError("Bundle path must be a Path.")
        if not isinstance(self.manifest_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.manifest_sha256
        ):
            raise ValueError("Configure a trusted manifest SHA-256 as 64 lowercase hex characters.")
        validate_cache_settings(
            self.cache_max_entries, self.cache_max_bytes, self.cache_ttl_seconds
        )
        if type(self.busy_policy) is not str or self.busy_policy not in (
            "reject",
            "recent_popularity",
        ):
            raise ValueError("Busy policy must be reject or recent_popularity.")

    @classmethod
    def from_environment(cls):
        path, pin = os.environ.get("RECSYS_BUNDLE_PATH"), os.environ.get("RECSYS_MANIFEST_SHA256")
        if not path or not pin:
            raise ValueError("RECSYS_BUNDLE_PATH and RECSYS_MANIFEST_SHA256 are required.")
        return cls(Path(path), pin)
