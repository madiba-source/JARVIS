"""Calendar settings. Bounded, frozen, env overridable via JARVIS_CALENDAR__*."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_INT_FIELDS = (
    "max_events_returned", "max_task_results", "max_occurrences_per_query",
    "max_recurrence_horizon_days", "max_event_description_chars",
    "max_reminders_per_cycle", "max_workflow_steps", "max_workflow_depth",
    "max_concurrent_workflows", "max_ics_bytes", "max_ics_events",
)


class CalendarConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    timezone: str = "UTC"
    max_events_returned: int = Field(default=128, ge=1, le=4096)
    max_task_results: int = Field(default=128, ge=1, le=4096)
    max_occurrences_per_query: int = Field(default=256, ge=1, le=4096)
    max_recurrence_horizon_days: int = Field(default=366, ge=1, le=3650)
    max_event_description_chars: int = Field(default=8192, ge=16, le=32768)
    max_reminders_per_cycle: int = Field(default=128, ge=1, le=4096)
    scheduler_enabled: bool = True
    scheduler_poll_max_seconds: float = Field(default=300.0, ge=1.0, le=86400.0)
    scheduler_grace_seconds: float = Field(default=60.0, ge=0.0, le=86400.0)
    max_workflow_steps: int = Field(default=32, ge=1, le=256)
    max_workflow_depth: int = Field(default=8, ge=1, le=32)
    max_workflow_runtime_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    max_concurrent_workflows: int = Field(default=2, ge=1, le=16)
    max_ics_bytes: int = Field(default=1_048_576, ge=1024, le=64 * 1024 * 1024)
    max_ics_events: int = Field(default=512, ge=1, le=65536)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid IANA timezone")
        return value

    @model_validator(mode="after")
    def reject_boolean_integers(self) -> CalendarConfig:
        for field in _INT_FIELDS:
            value = getattr(self, field)
            if isinstance(value, bool):
                raise ValueError(f"{field} must be an integer, not a boolean")
        return self