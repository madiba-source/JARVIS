"""Immutable schemas at the calendar trust boundary.

All datetimes are timezone-aware. Content (titles, descriptions, notes) is
never used to grant authority; it is validated and bounded only.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, TypeAlias
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TITLE_MAX = 256
DESCRIPTION_MAX = 8192
NOTE_MAX = 4096
DateType: TypeAlias = date


def aware(tzinfo: str | None = None) -> datetime:
    return datetime.now(timezone.utc)


def iso_aware(value: datetime) -> str:
    return value.isoformat()


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False)


def check_aware(value: datetime) -> None:
    if value.tzinfo is None or not 1970 <= value.year <= 2100:
        raise ValueError("timezone-aware datetime in supported range required")


def check_date(value: date) -> None:
    if not 1970 <= value.year <= 2100:
        raise ValueError("date outside supported range")


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


_ISO_WEEKDAY = {Weekday.MONDAY: 0, Weekday.TUESDAY: 1, Weekday.WEDNESDAY: 2,
                Weekday.THURSDAY: 3, Weekday.FRIDAY: 4, Weekday.SATURDAY: 5,
                Weekday.SUNDAY: 6}


def weekday_of(day: date) -> Weekday:
    return list(_ISO_WEEKDAY)[day.weekday()]


def weekday_index(day: Weekday) -> int:
    return _ISO_WEEKDAY[day]


class EventStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventKind(StrEnum):
    EVENT = "event"
    NOTE = "note"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    FIRED = "fired"
    CANCELLED = "cancelled"


class ReminderTargetKind(StrEnum):
    EVENT = "event"
    TASK = "task"


class ConflictKind(StrEnum):
    EVENT_EVENT = "event_event"
    EVENT_TIMETABLE = "event_timetable"
    TIMETABLE_TIMETABLE = "timetable_timetable"
    TASK_DEADLINE = "task_deadline"


class QueryKind(StrEnum):
    DAY = "day"
    WEEK = "week"
    RANGE = "range"
    UPCOMING = "upcoming"
    FREE_TIME = "free_time"
    NEXT_OCCURRENCE = "next_occurrence"
    TASKS = "tasks"
    TASKS_OVERDUE = "tasks_overdue"
    NEXT_CLASS = "next_class"


class RecurrenceFreq(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class WorkflowStepKind(StrEnum):
    READ_SCHEDULE = "read_schedule"
    READ_DEADLINES = "read_deadlines"
    READ_UPCOMING = "read_upcoming"
    ANNOUNCE = "announce"
    NESTED = "nested"


class TriggerType(StrEnum):
    AT_TIME = "at_time"
    BEFORE_EVENT = "before_event"
    AFTER_EVENT = "after_event"


def normalize_text(value: str) -> str:
    return " ".join(value.split())


class TextContent:
    @staticmethod
    def safe(value: str) -> str:
        if any(ord(c) == 0 for c in value):
            raise ValueError("null byte rejected")
        return value


class TimeRange(Schema):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        check_aware(value)
        return value

    @model_validator(mode="after")
    def ordering(self) -> TimeRange:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    def overlaps(self, other: TimeRange) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, instant: datetime) -> bool:
        return self.start <= instant < self.end

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class CalendarEvent(Schema):
    event_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    kind: EventKind = EventKind.EVENT
    all_day: bool = False
    start: datetime | None = None
    end: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = "UTC"
    recurrence_id: UUID | None = None
    status: EventStatus = EventStatus.ACTIVE
    source: str = "calendar"
    created_at: datetime = Field(default_factory=aware)
    updated_at: datetime = Field(default_factory=aware)
    version: int = Field(default=1, ge=1, le=1_000_000)

    @field_validator("title")
    @classmethod
    def safe_title(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)

    @field_validator("description")
    @classmethod
    def safe_description(cls, value: str) -> str:
        TextContent.safe(value)
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid IANA timezone")
        return value

    @field_validator("start", "end")
    @classmethod
    def aware_fields(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def date_fields(cls, value: date | None) -> date | None:
        if value is not None:
            check_date(value)
        return value

    @model_validator(mode="after")
    def timing(self) -> CalendarEvent:
        if self.all_day:
            if self.start is not None or self.end is not None:
                raise ValueError("timed fields forbidden on all-day events")
            if self.start_date is None or self.end_date is None:
                raise ValueError("all-day events require start_date and end_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date must be >= start_date")
        else:
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("date fields forbidden on timed events")
            if self.start is None or self.end is None:
                raise ValueError("timed events require start and end")
            if self.end <= self.start:
                raise ValueError("end must be after start")
        if self.updated_at < self.created_at:
            raise ValueError("updated before creation")
        return self

    def day_date(self) -> date:
        return self.start_date or self.start.date()

    def as_time_range(self, tz: ZoneInfo | None = None) -> TimeRange | None:
        if self.all_day:
            zone = tz or ZoneInfo(self.timezone)
            start = datetime.combine(self.start_date, time.min, tzinfo=zone)
            end = datetime.combine(self.end_date, time.max, tzinfo=zone) + timedelta(seconds=1)
            return TimeRange(start=start, end=end)
        return TimeRange(start=self.start, end=self.end) if self.start and self.end else None


class CalendarRecurrence(Schema):
    recurrence_id: UUID = Field(default_factory=uuid4)
    freq: RecurrenceFreq
    interval: int = Field(default=1, ge=1, le=366)
    by_day: tuple[Weekday, ...] = Field(default=(), max_length=7)
    by_month_day: int | None = Field(default=None, ge=1, le=31)
    count: int | None = Field(default=None, ge=1, le=10_000)
    until: datetime | None = None
    dtstart: datetime
    created_at: datetime = Field(default_factory=aware)

    @field_validator("dtstart", "until")
    @classmethod
    def aware_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @model_validator(mode="after")
    def constraints(self) -> CalendarRecurrence:
        if self.count is None and self.until is None:
            raise ValueError("unbounded recurrence rejected: count or until required")
        if self.until is not None and self.until <= self.dtstart:
            raise ValueError("recurrence until must follow dtstart")
        if self.by_day and self.freq is RecurrenceFreq.WEEKLY and len(self.by_day) > 7:
            raise ValueError("by_day exceeds a week")
        if self.by_month_day is not None and self.freq is not RecurrenceFreq.MONTHLY:
            raise ValueError("by_month_day requires monthly frequency")
        if self.freq is RecurrenceFreq.DAILY and self.by_day:
            raise ValueError("by_day not supported for daily recurrence")
        return self

    def is_bounded(self) -> bool:
        return self.count is not None or self.until is not None


class CalendarReminder(Schema):
    reminder_id: UUID = Field(default_factory=uuid4)
    target_id: UUID
    target_kind: ReminderTargetKind
    remind_at: datetime
    notification_type: str = Field(default="announce", min_length=1, max_length=64)
    status: ReminderStatus = ReminderStatus.PENDING
    created_at: datetime = Field(default_factory=aware)
    fired_at: datetime | None = None

    @field_validator("remind_at", "fired_at", "created_at")
    @classmethod
    def aware_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @model_validator(mode="after")
    def coherence(self) -> CalendarReminder:
        if self.status is ReminderStatus.FIRED and self.fired_at is None:
            raise ValueError("fired reminders require fired_at")
        if self.status is ReminderStatus.PENDING and self.fired_at is not None:
            raise ValueError("pending reminders cannot be fired")
        return self


class CalendarTask(Schema):
    task_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    due_at: datetime | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=aware)
    completed_at: datetime | None = None
    subject: str = Field(default="", max_length=192)
    project: str = Field(default="", max_length=192)
    tags: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("title")
    @classmethod
    def safe_title(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)

    @field_validator("description")
    @classmethod
    def safe_description(cls, value: str) -> str:
        TextContent.safe(value)
        return value

    @field_validator("subject", "project")
    @classmethod
    def short_label(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)

    @field_validator("due_at", "completed_at", "created_at")
    @classmethod
    def aware_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @field_validator("tags")
    @classmethod
    def tag_ok(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(item) > 96 for item in value):
            raise ValueError("tag too long")
        return tuple(normalize_text(item) for item in value)

    @model_validator(mode="after")
    def coherence(self) -> CalendarTask:
        if self.status is TaskStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed tasks require completed_at")
        if self.status is not TaskStatus.COMPLETED and self.completed_at is not None:
            raise ValueError("completed_at set on non-completed task")
        return self


class Subject(Schema):
    subject_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=192)
    category: str = Field(default="", max_length=192)

    @field_validator("name", "category")
    @classmethod
    def label(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)


class TimetableEntry(Schema):
    entry_id: UUID = Field(default_factory=uuid4)
    subject: str = Field(min_length=1, max_length=192)
    teacher: str = Field(default="", max_length=192)
    room: str = Field(default="", max_length=96)
    weekday: Weekday
    start_time: time
    end_time: time
    term: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=NOTE_MAX)

    @field_validator("subject", "teacher", "room", "term")
    @classmethod
    def label(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)

    @field_validator("notes")
    @classmethod
    def safe_notes(cls, value: str) -> str:
        TextContent.safe(value)
        return value

    @model_validator(mode="after")
    def ordering(self) -> TimetableEntry:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ScheduleOccurrence(Schema):
    entry_id: UUID
    subject: str
    teacher: str = ""
    room: str = ""
    date: DateType
    start: datetime
    end: datetime
    term: str = ""
    notes: str = ""

    @field_validator("start", "end")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        check_aware(value)
        return value

    @model_validator(mode="after")
    def ordering(self) -> ScheduleOccurrence:
        if self.end <= self.start:
            raise ValueError("occurrence end must follow start")
        return self


class ScheduleConflict(Schema):
    conflict_id: UUID = Field(default_factory=uuid4)
    kind: ConflictKind
    start: datetime
    end: datetime
    parties: tuple[str, ...] = Field(default=(), max_length=8)
    detail: str = Field(default="", max_length=256)

    @field_validator("start", "end")
    @classmethod
    def aware_times(cls, value: datetime) -> datetime:
        check_aware(value)
        return value

    @model_validator(mode="after")
    def ordering(self) -> ScheduleConflict:
        if self.end <= self.start:
            raise ValueError("conflict end must follow start")
        return self


class DaySchedule(Schema):
    date: DateType
    timezone: str = "UTC"
    events: tuple[CalendarEvent, ...] = Field(default=(), max_length=256)
    occurrences: tuple[ScheduleOccurrence, ...] = Field(default=(), max_length=256)
    tasks: tuple[CalendarTask, ...] = Field(default=(), max_length=256)
    conflicts: tuple[ScheduleConflict, ...] = Field(default=(), max_length=256)


class WeekSchedule(Schema):
    start_date: date
    end_date: date
    timezone: str = "UTC"
    days: tuple[DaySchedule, ...] = Field(default=(), max_length=7)


class CalendarQuery(Schema):
    kind: QueryKind
    date: DateType | None = None
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=16, ge=1, le=128)
    minimum_duration_minutes: int = Field(default=0, ge=0, le=24 * 60)
    subject: str = Field(default="", max_length=192)
    project: str = Field(default="", max_length=192)

    @field_validator("start", "end")
    @classmethod
    def aware_times(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @model_validator(mode="after")
    def interval(self) -> CalendarQuery:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("invalid query interval")
        if self.kind is QueryKind.DAY and self.date is None:
            raise ValueError("day queries require a date")
        return self


class CalendarMutation(Schema):
    mutation_id: UUID = Field(default_factory=uuid4)
    operation: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(default_factory=dict, max_length=64)
    created_at: datetime = Field(default_factory=aware)


class WorkflowStep(Schema):
    step_id: UUID = Field(default_factory=uuid4)
    kind: WorkflowStepKind
    key: str = Field(default="", max_length=96)
    target: str = Field(default="", max_length=256)
    args: dict[str, object] = Field(default_factory=dict, max_length=32)

    @field_validator("key", "target")
    @classmethod
    def short(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)


class WorkflowDefinition(Schema):
    workflow_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=192)
    steps: tuple[WorkflowStep, ...] = Field(default=(), max_length=256)
    enabled: bool = True
    created_at: datetime = Field(default_factory=aware)

    @field_validator("name")
    @classmethod
    def short(cls, value: str) -> str:
        TextContent.safe(value)
        return normalize_text(value)

    @property
    def step_count(self) -> int:
        return len(self.steps)


class WorkflowTrigger(Schema):
    trigger_id: UUID = Field(default_factory=uuid4)
    workflow_id: UUID
    trigger_type: TriggerType
    at_time: time | None = None
    before_event: UUID | None = None
    after_event: UUID | None = None
    enabled: bool = True
    last_fired_at: datetime | None = None

    @field_validator("last_fired_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            check_aware(value)
        return value

    @model_validator(mode="after")
    def coherence(self) -> WorkflowTrigger:
        if self.trigger_type is TriggerType.AT_TIME:
            if self.at_time is None:
                raise ValueError("at_time triggers require at_time")
        else:
            if self.before_event is None and self.after_event is None:
                raise ValueError("event triggers require a target event")
        if self.before_event is not None and self.after_event is not None:
            raise ValueError("event trigger cannot be both before and after")
        return self


class WorkflowStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class WorkflowResult(Schema):
    workflow_id: UUID
    status: WorkflowStatus
    steps_executed: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=2048)
    error_type: str = Field(default="", max_length=128)

    @field_validator("summary")
    @classmethod
    def safe_summary(cls, value: str) -> str:
        return value.replace("\x00", "")