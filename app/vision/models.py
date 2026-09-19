from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import Field, StrictFloat, StrictInt, StrictStr

from app.agent.models import Identifier, Schema, now


class VisionState(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"


class VisionRegion(Schema):
    x: StrictInt = Field(ge=0, le=3840)
    y: StrictInt = Field(ge=0, le=2160)
    width: StrictInt = Field(ge=1, le=3840)
    height: StrictInt = Field(ge=1, le=2160)
    label: StrictStr = Field(default="", max_length=128)
    confidence: StrictFloat = Field(default=0, ge=0, le=1)


class VisionObservation(Schema):
    observation_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    observed_at: datetime = Field(default_factory=now)
    source: str = Field(default="screen", max_length=32)
    trust: str = "UNTRUSTED_EXTERNAL_DATA"
    image_width: StrictInt = Field(ge=1, le=3840)
    image_height: StrictInt = Field(ge=1, le=2160)
    regions: tuple[VisionRegion, ...] = Field(default=(), max_length=128)
    text: str = Field(default="", max_length=16_384)
    confidence: StrictFloat = Field(default=0, ge=0, le=1)
    content_hash: str = Field(default="", max_length=64)