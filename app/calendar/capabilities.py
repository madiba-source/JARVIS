"""Typed calendar capabilities on the Phase 03/04 policy gateway.

Each tool is registered with exactly one operation and a self-contained
executor so admission, confirmation and execution work identically through the
gateway and through direct use. No schema reads user content as authority.
"""

from __future__ import annotations

import threading
from datetime import date, date as DateType
from datetime import datetime, time
from typing import Any
from uuid import UUID

from pydantic import Field, field_serializer
from zoneinfo import ZoneInfo

from app.core.events import EventBus
from app.execution.models import ExecutionCode, ExecutionResult
from app.observability.events import EventType, StructuredEvent
from app.policy.enums import AuthorizationLevel, DecisionState
from app.policy.models import AuditEvent, ToolRequest
from app.policy.registry import ToolDefinition
from app.policy.service import PolicyEngineService

from app.calendar.config import CalendarConfig
from app.calendar.models import (
    Schema, Weekday, EventKind, TaskPriority, ReminderTargetKind,
    WorkflowDefinition, WorkflowStep, WorkflowStepKind,
)
from app.calendar.service import CalendarService


def _parse_dt(value: str | None, tz: ZoneInfo | None = None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if tz is None:
            raise ValueError("naive datetime requires a timezone")
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class _Wire:
    @field_serializer("date", "start_date", "end_date", when_used="always",
                      check_fields=False)
    def _date(self, value, _info):
        return value.isoformat() if value is not None else None

    @field_serializer("start", "end", "due_at", "to_start", "to", "remind_at",
                      "until", when_used="always", check_fields=False)
    def _datetime(self, value, _info):
        return value.isoformat() if value is not None else None


class DayQueryArgs(_Wire, Schema):
    date: DateType | None = None
    timezone: str | None = None


class WeekQueryArgs(_Wire, Schema):
    date: DateType | None = None
    timezone: str | None = None


class RangeQueryArgs(_Wire, Schema):
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=16, ge=1, le=128)


class UpcomingArgs(Schema):
    limit: int = Field(default=16, ge=1, le=128)


class TimetableArgs(Schema):
    weekday: Weekday | None = None
    term: str = Field(default="", max_length=64)


class FreeTimeArgs(_Wire, Schema):
    start: datetime
    end: datetime
    minimum_duration_minutes: int = Field(default=0, ge=0, le=24 * 60)


class NextClassArgs(_Wire, Schema):
    start: datetime | None = None


class CreateEventArgs(_Wire, Schema):
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8192)
    all_day: bool = False
    start: datetime | None = None
    end: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = None
    forbidden_arg: str = ""

    @field_serializer("forbidden_arg", when_used="always")
    def _ban(self, value, _info):
        if value:
            raise ValueError("not allowed")
        return ""


class UpdateEventArgs(_Wire, Schema):
    event_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=8192)
    all_day: bool | None = None
    start: datetime | None = None
    end: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_serializer("event_id", when_used="always")
    def _eid(self, value: UUID, _info) -> str:
        return str(value)


class MoveEventArgs(_Wire, Schema):
    event_id: UUID
    to_start: datetime

    @field_serializer("event_id", when_used="always")
    def _eid(self, value: UUID, _info) -> str:
        return str(value)


class ResizeEventArgs(Schema):
    event_id: UUID
    duration_minutes: int = Field(ge=1, le=24 * 60)

    @field_serializer("event_id", when_used="always")
    def _eid(self, value: UUID, _info) -> str:
        return str(value)


class EventIdArgs(Schema):
    event_id: UUID

    @field_serializer("event_id", when_used="always")
    def _eid(self, value: UUID, _info) -> str:
        return str(value)


class CreateTaskArgs(_Wire, Schema):
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8192)
    due_at: datetime | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    subject: str = Field(default="", max_length=192)
    project: str = Field(default="", max_length=192)
    tags: tuple[str, ...] = Field(default=(), max_length=16)


class TaskIdArgs(Schema):
    task_id: UUID

    @field_serializer("task_id", when_used="always")
    def _tid(self, value: UUID, _info) -> str:
        return str(value)


class PostponeTaskArgs(_Wire, Schema):
    task_id: UUID
    to: datetime

    @field_serializer("task_id", when_used="always")
    def _tid(self, value: UUID, _info) -> str:
        return str(value)


class CreateReminderArgs(_Wire, Schema):
    target_id: UUID
    target_kind: ReminderTargetKind
    remind_at: datetime
    notification_type: str = Field(default="announce", max_length=64)

    @field_serializer("target_id", when_used="always")
    def _tid(self, value: UUID, _info) -> str:
        return str(value)


class ReminderIdArgs(Schema):
    reminder_id: UUID

    @field_serializer("reminder_id", when_used="always")
    def _rid(self, value: UUID, _info) -> str:
        return str(value)


class CreateWorkflowArgs(Schema):
    name: str = Field(min_length=1, max_length=192)
    steps: tuple[WorkflowStepArgs, ...] = Field(default=(), max_length=32)
    enabled: bool = True


class WorkflowStepArgs(Schema):
    kind: WorkflowStepKind
    key: str = Field(default="", max_length=96)
    target: str = Field(default="", max_length=256)
    args: dict[str, str] = Field(default_factory=dict, max_length=32)


class RunWorkflowArgs(Schema):
    workflow_id: UUID

    @field_serializer("workflow_id", when_used="always")
    def _wid(self, value: UUID, _info) -> str:
        return str(value)


class WorkflowIdArgs(Schema):
    workflow_id: UUID

    @field_serializer("workflow_id", when_used="always")
    def _wid(self, value: UUID, _info) -> str:
        return str(value)


class CalendarPolicyService(PolicyEngineService):
    """Governed calendar capabilities over the trusted CalendarService."""

    def __init__(self, calendar: CalendarService, config: CalendarConfig,
                 event_bus: EventBus | None = None) -> None:
        self._calendar = calendar
        self._config = config
        self.event_bus = event_bus or EventBus()
        self._execution_slots = threading.BoundedSemaphore(config.max_concurrent_workflows)
        self._operation_context = threading.local()
        self.limits = None
        super().__init__()

    # ---- read executors ----

    def _day(self, arguments: dict) -> dict:
        query_date = _parse_date(arguments.get("date")) or self._calendar.clock.today(self._calendar.timezone)
        schedule = self._calendar.day_schedule(query_date,
                                               timezone=arguments.get("timezone"))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="day schedule read",
                               data=schedule.model_dump(mode="json")).model_dump()

    def _week(self, arguments: dict) -> dict:
        query_date = _parse_date(arguments.get("date")) or self._calendar.clock.today(self._calendar.timezone)
        schedule = self._calendar.week_schedule(query_date,
                                                timezone=arguments.get("timezone"))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="week schedule read",
                               data=schedule.model_dump(mode="json")).model_dump()

    def _range(self, arguments: dict) -> dict:
        events = self._calendar.list_events(
            since=_parse_dt(arguments.get("start")),
            until=_parse_dt(arguments.get("end")),
            limit=arguments.get("limit", 16))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="events read",
                               data={"events": [e.model_dump(mode="json") for e in events]}).model_dump()

    def _upcoming(self, arguments: dict) -> dict:
        events = self._calendar.upcoming(limit=arguments.get("limit", 16))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="upcoming events read",
                               data={"events": [e.model_dump(mode="json") for e in events]}).model_dump()

    def _timetable(self, arguments: dict) -> dict:
        entries = self._calendar.timetable(weekday=arguments.get("weekday"),
                                           term=arguments.get("term", ""))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="timetable read",
                               data={"entries": [e.model_dump(mode="json") for e in entries]}).model_dump()

    def _free_time(self, arguments: dict) -> dict:
        slots = self._calendar.find_free_time(
            _parse_dt(arguments["start"], self._calendar.timezone),
            _parse_dt(arguments["end"], self._calendar.timezone),
            arguments.get("minimum_duration_minutes", 0))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="free time computed",
                               data={"slots": [s.model_dump(mode="json") for s in slots]}).model_dump()

    def _next_class(self, arguments: dict) -> dict:
        after = _parse_dt(arguments.get("start"))
        occurrence = self._calendar.next_class(after)
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="next class read",
                               data={"occurrence": occurrence.model_dump(mode="json") if occurrence else None}).model_dump()

    # ---- mutation executors ----

    def _create_event(self, arguments: dict) -> dict:
        event = self._calendar.create_event(
            title=arguments["title"], description=arguments.get("description", ""),
            all_day=arguments.get("all_day", False),
            start=_parse_dt(arguments.get("start"), self._calendar.timezone),
            end=_parse_dt(arguments.get("end"), self._calendar.timezone),
            start_date=_parse_date(arguments.get("start_date")),
            end_date=_parse_date(arguments.get("end_date")),
            timezone=arguments.get("timezone"), source="agent")
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event created",
                               data={"event_id": str(event.event_id)}).model_dump()

    def _update_event(self, arguments: dict) -> dict:
        event = self._calendar.update_event(
            str(arguments["event_id"]),
            title=arguments.get("title"), description=arguments.get("description"),
            all_day=arguments.get("all_day"),
            start=_parse_dt(arguments.get("start"), self._calendar.timezone),
            end=_parse_dt(arguments.get("end"), self._calendar.timezone),
            start_date=_parse_date(arguments.get("start_date")),
            end_date=_parse_date(arguments.get("end_date")))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event updated",
                               data={"event_id": str(event.event_id)}).model_dump()

    def _move_event(self, arguments: dict) -> dict:
        event = self._calendar.move_event(str(arguments["event_id"]),
                                          to_start=_parse_dt(arguments["to_start"], self._calendar.timezone))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event moved",
                               data={"event_id": str(event.event_id)}).model_dump()

    def _resize_event(self, arguments: dict) -> dict:
        event = self._calendar.resize_event(str(arguments["event_id"]),
                                            duration_minutes=arguments["duration_minutes"])
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event resized",
                               data={"event_id": str(event.event_id)}).model_dump()

    def _cancel_event(self, arguments: dict) -> dict:
        event = self._calendar.cancel_event(str(arguments["event_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event cancelled",
                               data={"event_id": str(event.event_id)}).model_dump()

    def _delete_event(self, arguments: dict) -> dict:
        self._calendar.delete_event(str(arguments["event_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="event deleted",
                               data={}).model_dump()

    def _create_task(self, arguments: dict) -> dict:
        task = self._calendar.create_task(
            title=arguments["title"], description=arguments.get("description", ""),
            due_at=_parse_dt(arguments.get("due_at"), self._calendar.timezone),
            priority=arguments.get("priority", "medium"),
            subject=arguments.get("subject", ""), project=arguments.get("project", ""),
            tags=tuple(arguments.get("tags", ())))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="task created",
                               data={"task_id": str(task.task_id)}).model_dump()

    def _complete_task(self, arguments: dict) -> dict:
        task = self._calendar.complete_task(str(arguments["task_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="task completed",
                               data={"task_id": str(task.task_id)}).model_dump()

    def _postpone_task(self, arguments: dict) -> dict:
        task = self._calendar.postpone_task(str(arguments["task_id"]),
                                            to=_parse_dt(arguments["to"], self._calendar.timezone))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="task postponed",
                               data={"task_id": str(task.task_id)}).model_dump()

    def _delete_task(self, arguments: dict) -> dict:
        self._calendar.delete_task(str(arguments["task_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="task deleted",
                               data={}).model_dump()

    def _create_reminder(self, arguments: dict) -> dict:
        reminder = self._calendar.create_reminder(
            target_id=str(arguments["target_id"]),
            target_kind=arguments["target_kind"],
            remind_at=_parse_dt(arguments["remind_at"], self._calendar.timezone),
            notification_type=arguments.get("notification_type", "announce"))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="reminder scheduled",
                               data={"reminder_id": str(reminder.reminder_id)}).model_dump()

    def _cancel_reminder(self, arguments: dict) -> dict:
        reminder = self._calendar.cancel_reminder(str(arguments["reminder_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="reminder cancelled",
                               data={"reminder_id": str(reminder.reminder_id)}).model_dump()

    def _create_workflow(self, arguments: dict) -> dict:
        steps = tuple(WorkflowStep(kind=item["kind"], key=item.get("key", ""),
                                   target=item.get("target", ""),
                                   args=dict(item.get("args", {})))
                      for item in arguments.get("steps", ()))
        definition = self._calendar.save_workflow(WorkflowDefinition(
            name=arguments["name"], steps=steps,
            enabled=arguments.get("enabled", True)))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="workflow saved",
                               data={"workflow_id": str(definition.workflow_id)}).model_dump()

    def _run_workflow(self, arguments: dict) -> dict:
        definition = self._calendar.get_workflow(str(arguments["workflow_id"]))
        if definition is None:
            return ExecutionResult(code=ExecutionCode.INVALID_REQUEST,
                                   message="workflow not found", data={}).model_dump()
        result = self._calendar.run_workflow(definition)
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="workflow executed",
                               data=result.model_dump(mode="json")).model_dump()

    def _delete_workflow(self, arguments: dict) -> dict:
        self._calendar.delete_workflow(str(arguments["workflow_id"]))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="workflow deleted",
                               data={}).model_dump()

    # ---- registration ----

    def _register_defaults(self) -> None:
        definitions = (
            ("calendar_read_day", DayQueryArgs, self._day, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_read_week", WeekQueryArgs, self._week, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_read_range", RangeQueryArgs, self._range, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_read_upcoming", UpcomingArgs, self._upcoming, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_read_timetable", TimetableArgs, self._timetable, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_find_free_time", FreeTimeArgs, self._free_time, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_next_class", NextClassArgs, self._next_class, AuthorizationLevel.L0_READ_ONLY),
            ("calendar_create_event", CreateEventArgs, self._create_event, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_update_event", UpdateEventArgs, self._update_event, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_move_event", MoveEventArgs, self._move_event, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_resize_event", ResizeEventArgs, self._resize_event, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_cancel_event", EventIdArgs, self._cancel_event, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_delete_event", EventIdArgs, self._delete_event, AuthorizationLevel.L3_DESTRUCTIVE),
            ("calendar_create_task", CreateTaskArgs, self._create_task, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_complete_task", TaskIdArgs, self._complete_task, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_postpone_task", PostponeTaskArgs, self._postpone_task, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_delete_task", TaskIdArgs, self._delete_task, AuthorizationLevel.L3_DESTRUCTIVE),
            ("calendar_create_reminder", CreateReminderArgs, self._create_reminder, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_cancel_reminder", ReminderIdArgs, self._cancel_reminder, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_create_workflow", CreateWorkflowArgs, self._create_workflow, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_run_workflow", RunWorkflowArgs, self._run_workflow, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
            ("calendar_delete_workflow", WorkflowIdArgs, self._delete_workflow, AuthorizationLevel.L3_DESTRUCTIVE),
        )
        for tool_id, schema, executor, level in definitions:
            confirmation = level is not AuthorizationLevel.L0_READ_ONLY
            tool = ToolDefinition(
                tool_id=tool_id, name=tool_id,
                description="Governed calendar endpoint",
                authorization_level=level, requires_confirmation=confirmation,
                supported_operations=(tool_id,), operation_models={tool_id: schema},
                executor=self._executor(tool_id, executor),
                modify_user_data=confirmation,
            )
            self.registry.register_tool(tool)
        self.registry.freeze()

    def _executor(self, tool_id: str, fn):
        def dispatch(arguments: dict[str, Any]) -> dict[str, Any]:
            result = fn(arguments)
            return ExecutionResult.model_validate(result).model_dump()
        return dispatch

    # ---- execution ----

    def execute(self, request: ToolRequest) -> ExecutionResult:
        definition = self.registry.get_immutable_definition(request.tool_name)
        if definition is None or request.operation not in definition.operation_models:
            return ExecutionResult(code=ExecutionCode.DENIED,
                                   message="capability is not registered")
        decision, permit = self.process_request(request)
        if decision.decision is DecisionState.REQUIRE_CONFIRMATION:
            return ExecutionResult(code=ExecutionCode.CONFIRMATION_REQUIRED,
                                   message="explicit confirmation required")
        if decision.decision is not DecisionState.ALLOW or permit is None:
            return ExecutionResult(code=ExecutionCode.DENIED, message=decision.reason)
        try:
            result = self.execute_with_permit(request, permit)
            typed_result = ExecutionResult.model_validate(result)
            self.event_bus.publish(StructuredEvent(
                event_type=EventType.TOOL_COMPLETED if typed_result.success else EventType.TOOL_FAILED,
                component="calendar", source="CalendarPolicyService.execute",
                request_id=request.request_id, tool_id=request.tool_name,
                operation=request.operation, success=typed_result.success))
            return typed_result
        except Exception as error:
            return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED,
                                   message=type(error).__name__)

    def close(self) -> None:
        pass