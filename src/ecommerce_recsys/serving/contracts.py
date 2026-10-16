"""Explicit HTTP inputs, outputs and operator-controlled snapshot configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Version = Annotated[str, StringConstraints(min_length=1, max_length=80)]
OutputLimit = Annotated[int, Field(ge=1, le=20)]
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

    def __post_init__(self):
        if not isinstance(self.bundle_path, Path):
            raise ValueError("Bundle path must be a Path.")
        if not isinstance(self.manifest_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.manifest_sha256
        ):
            raise ValueError("Configure a trusted manifest SHA-256 as 64 lowercase hex characters.")

    @classmethod
    def from_environment(cls):
        path, pin = os.environ.get("RECSYS_BUNDLE_PATH"), os.environ.get("RECSYS_MANIFEST_SHA256")
        if not path or not pin:
            raise ValueError("RECSYS_BUNDLE_PATH and RECSYS_MANIFEST_SHA256 are required.")
        return cls(Path(path), pin)
