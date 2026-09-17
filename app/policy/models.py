"""Typed policy request, decision, and audit models."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import AuthorizationLevel, DecisionState


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    authorization_level: AuthorizationLevel
    arguments: dict[str, Any] = Field(default_factory=dict)
    originating_subsystem: str = Field(min_length=1)
    requested_resource_budget: dict[str, float] | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmation_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_id", "tool_name", "operation", "originating_subsystem")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    decision: DecisionState
    tool_name: str
    authorization_level: AuthorizationLevel | None
    requires_confirmation: bool
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    request_id: str
    tool_id: str
    requested_operation: str
    decision: DecisionState
    authorization_level: AuthorizationLevel | None
    confirmation_state: str
    resource_decision: str
    reason: str
    source_subsystem: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
