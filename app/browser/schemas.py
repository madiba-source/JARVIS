"""Policy registry argument schemas for browser capabilities."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from .models import LocatorStrategy


class BrowserBaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserNavigateArgs(BrowserBaseArgs):
    request_id: StrictStr = Field(min_length=1, max_length=64)
    url: StrictStr = Field(min_length=1, max_length=4096)
    timeout_ms: StrictInt = Field(default=30_000, ge=100, le=120_000)


class BrowserInspectArgs(BrowserBaseArgs):
    request_id: StrictStr = Field(min_length=1, max_length=64)
    max_chars: StrictInt = Field(default=16_384, ge=256, le=131_072)


class BrowserScreenshotArgs(BrowserBaseArgs):
    request_id: StrictStr = Field(min_length=1, max_length=64)
    full_page: StrictBool = False
    max_bytes: StrictInt = Field(default=4_194_304, ge=1024, le=16_777_216)


class BrowserTargetArgs(BrowserBaseArgs):
    request_id: StrictStr = Field(min_length=1, max_length=64)
    strategy: LocatorStrategy
    target: StrictStr = Field(min_length=1, max_length=512)
    timeout_ms: StrictInt = Field(default=10_000, ge=100, le=60_000)


class BrowserTypeArgs(BrowserTargetArgs):
    text: StrictStr = Field(min_length=1, max_length=4096)