"""Typed model request/response contracts.

The runtime never depends on a specific client library. Providers translate
between these types and whatever transport they use, and they report failure as
a state rather than raising. A model response is data: it can propose a plan,
and it can never authorize one.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, StrictBool

from .models import Schema

MAX_PROMPT_CHARS = 32_768
MAX_RESPONSE_CHARS = 65_536


class ModelRole(StrEnum):
    PLANNING = "planning"
    REPAIR = "repair"


class ModelResponseState(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    OVERSIZED = "oversized"
    RATE_LIMITED = "rate_limited"


class ModelRequest(Schema):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    max_output_tokens: int = Field(default=1024, strict=True, ge=16, le=2048)
    timeout: float = Field(default=30, strict=True, ge=0.1, le=120)
    role: ModelRole = ModelRole.PLANNING
    structured: StrictBool = True
    model_hint: str = Field(default="", max_length=64)


class ModelResponse(Schema):
    state: ModelResponseState
    text: str = Field(default="", max_length=MAX_RESPONSE_CHARS)
    provider: str = Field(default="", max_length=64)
    model_name: str = Field(default="", max_length=128)
    tokens: int = Field(default=0, strict=True, ge=0, le=1_000_000)
    duration_ms: float = Field(default=0, ge=0, le=3_600_000)
    detail: str = Field(default="", max_length=256)

    @property
    def ok(self) -> bool:
        return self.state is ModelResponseState.OK


def ok_response(text: str, provider: str, model_name: str = "", tokens: int = 0,
                duration_ms: float = 0.0) -> ModelResponse:
    return ModelResponse(state=ModelResponseState.OK, text=text, provider=provider,
                         model_name=model_name[:128], tokens=max(0, int(tokens)),
                         duration_ms=max(0.0, float(duration_ms)))


def failed_response(state: ModelResponseState, provider: str, detail: str = "") -> ModelResponse:
    return ModelResponse(state=state, provider=provider, detail=str(detail)[:256])
