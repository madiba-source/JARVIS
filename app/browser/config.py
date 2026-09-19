"""Validated browser resource and privacy limits."""

from pydantic import Field, StrictBool

from app.agent.models import Schema


class BrowserConfig(Schema):
    enabled: StrictBool = True
    headed: StrictBool = True
    navigation_timeout_ms: int = Field(default=30_000, strict=True, ge=100, le=120_000)
    action_timeout_ms: int = Field(default=10_000, strict=True, ge=100, le=60_000)
    task_timeout_seconds: float = Field(default=120, strict=True, gt=0, le=600)
    max_sessions: int = Field(default=1, strict=True, ge=1, le=4)
    max_pages: int = Field(default=2, strict=True, ge=1, le=8)
    max_actions: int = Field(default=32, strict=True, ge=1, le=128)
    max_redirects: int = Field(default=8, strict=True, ge=0, le=32)
    max_extracted_chars: int = Field(default=16_384, strict=True, ge=256, le=131_072)
    max_elements: int = Field(default=128, strict=True, ge=1, le=512)
    max_screenshot_bytes: int = Field(default=4_194_304, strict=True, ge=1024, le=16_777_216)
    persistent_context: StrictBool = False
