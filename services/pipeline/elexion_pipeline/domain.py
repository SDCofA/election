from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceDefinition(BaseModel):
    id: str
    name: str
    base_url: str
    allowed_hosts: list[str]
    authority: str
    license_id: str
    license_name: str
    license_url: str
    attribution: str
    usage_scope: str = "Entire configured dataset"
    approved: bool
    allow_insecure_http: bool = False
    max_bytes: int = Field(gt=0)
    freshness_hours: int = Field(gt=0)
    content_types: list[str]

    @field_validator("allowed_hosts")
    @classmethod
    def hosts_cannot_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one allowed host is required")
        return [host.lower() for host in value]


class RawSnapshot(BaseModel):
    source_id: str
    source_url: str
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=0)
    content_type: str
    object_key: str
    object_uri: str
    etag: str | None = None
    last_modified: str | None = None
    license_id: str
    attribution: str
    usage_scope: str


class CanonicalObservation(BaseModel):
    jurisdiction_id: str
    metric: str
    observed_at: datetime
    released_at: datetime
    available_at: datetime
    value: float
    unit: str
    source_id: str
    source_snapshot_sha256: str
    revision: int = Field(default=0, ge=0)
    dimensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("available_at")
    @classmethod
    def available_after_release(cls, value: datetime, info):
        released_at = info.data.get("released_at")
        if released_at and value < released_at:
            raise ValueError("available_at cannot precede released_at")
        return value


class FetchResult(BaseModel):
    snapshot: RawSnapshot
    content: bytes = Field(exclude=True)
