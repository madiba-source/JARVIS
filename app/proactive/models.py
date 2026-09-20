"""Typed proactive event, workflow, and execution history models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProactiveEventSource(StrEnum):
    CALENDAR = "calendar"
    TIMETABLE = "timetable"
    TIMER = "timer"
    APPLICATION = "application"
    FILESYSTEM = "filesystem"
    SYSTEM = "system"
    INTERNAL = "internal"


class WorkflowState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProactiveEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ProactiveEventSource
    event_type: str = Field(min_length=1, max_length=128)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event time must be timezone-aware")
        return value


class ProactiveWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=128)
    trigger_at: datetime
    notification: str = Field(min_length=1, max_length=512)
    enabled: bool = True
    state: WorkflowState = WorkflowState.PENDING
    retry_count: int = Field(default=0, ge=0, le=3)
    max_retries: int = Field(default=0, ge=0, le=3)
    max_runtime_seconds: float = Field(default=10.0, gt=0, le=60.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: str | None = Field(default=None, max_length=256)

    @field_validator("trigger_at", "created_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("workflow time must be timezone-aware")
        return value


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    state: WorkflowState
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=256)
