"""Typed, ephemeral multimodal observations and sensitivity metadata."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Sensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    UNKNOWN = "unknown"


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=64)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = Field(default=None, ge=0, le=1)
    lifetime_seconds: float = Field(default=300, gt=0, le=3600)
    sensitivity: Sensitivity = Sensitivity.UNKNOWN
    content: str = Field(max_length=16_384)

    @property
    def expires_at(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.lifetime_seconds)

    def is_fresh(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) < self.expires_at


class ScreenObservation(ContextItem):
    source: str = "screen"
    observation_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)
    content_hash: str = Field(min_length=64, max_length=64)
    width: int = Field(ge=1, le=3840)
    height: int = Field(ge=1, le=2160)
    application: str | None = Field(default=None, max_length=256)
    window: str | None = Field(default=None, max_length=256)
    content: str = Field(default="", max_length=16_384)


class DocumentContent(ContextItem):
    source: str = "document"
    path: str = Field(min_length=1, max_length=4096)
    content_hash: str = Field(min_length=64, max_length=64)
    media_type: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=256)
    content: str = Field(max_length=1_048_576)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)

    @classmethod
    def from_text(cls, path: str, content: str, media_type: str, *, title: str = "", **metadata: str) -> "DocumentContent":
        return cls(path=path, content=content, title=title, content_hash=sha256(content.encode("utf-8")).hexdigest(), media_type=media_type, metadata=metadata)
