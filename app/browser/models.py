"""Typed browser inputs and bounded, untrusted observations."""

from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator

from app.agent.models import Identifier, Schema, now


class TrustLabel(StrEnum):
    UNTRUSTED_EXTERNAL_DATA = "UNTRUSTED_EXTERNAL_DATA"


class BrowserState(StrEnum):
    CLOSED = "closed"
    STARTING = "starting"
    READY = "ready"
    NAVIGATING = "navigating"
    OBSERVING = "observing"
    ACTING = "acting"
    VERIFYING = "verifying"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"
    SHUTTING_DOWN = "shutting_down"


class LocatorStrategy(StrEnum):
    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"


class BrowserRequest(Schema):
    request_id: Identifier


class NavigateRequest(BrowserRequest):
    url: StrictStr = Field(min_length=1, max_length=4096)
    timeout_ms: StrictInt = Field(default=30_000, ge=100, le=120_000)


class TargetRequest(BrowserRequest):
    strategy: LocatorStrategy
    target: StrictStr = Field(min_length=1, max_length=512)
    timeout_ms: StrictInt = Field(default=10_000, ge=100, le=60_000)


class TypeTextRequest(TargetRequest):
    text: StrictStr = Field(min_length=1, max_length=4096)


class ScrollRequest(BrowserRequest):
    direction: StrictStr = Field(pattern=r"^(up|down)$")
    amount: StrictInt = Field(default=600, ge=1, le=5000)


class ExtractRequest(BrowserRequest):
    max_chars: StrictInt = Field(default=16_384, ge=256, le=131_072)


class ScreenshotRequest(BrowserRequest):
    full_page: StrictBool = False
    max_bytes: StrictInt = Field(default=4_194_304, ge=1024, le=16_777_216)


class BrowserElement(Schema):
    role: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=256)
    locator: str = Field(default="", max_length=512)
    disabled: StrictBool = False


class BrowserObservation(Schema):
    observation_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    observed_at: datetime = Field(default_factory=now)
    source: str = Field(default="browser", max_length=32)
    trust: TrustLabel = TrustLabel.UNTRUSTED_EXTERNAL_DATA
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=512)
    visible_text: str = Field(default="", max_length=16_384)
    elements: tuple[BrowserElement, ...] = Field(default=(), max_length=128)
    content_hash: str = Field(default="", max_length=64)
    truncated: StrictBool = False

    @field_validator("visible_text", "title", mode="before")
    @classmethod
    def bound_text(cls, value: Any) -> str:
        return str(value or "")

    def refreshed(self, *, url: str, title: str, visible_text: str,
                  elements: tuple[BrowserElement, ...] = ()) -> "BrowserObservation":
        content = f"{url}\x00{title}\x00{visible_text}".encode("utf-8", "replace")
        return self.model_copy(update={"observation_id": uuid4().hex,
                                       "observed_at": datetime.now(timezone.utc),
                                       "url": url[:4096], "title": title[:512],
                                       "visible_text": visible_text[:16_384],
                                       "elements": elements[:128],
                                       "content_hash": sha256(content).hexdigest()})