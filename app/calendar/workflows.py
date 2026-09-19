"""Bounded workflow engine with a strict, typed step registry.

Workflows never execute arbitrary commands. Every step maps to a trusted,
bounded call; the engine enforces total steps, nesting depth, wall-clock
deadline and cooperative cancellation.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core.events import EventBus

from app.calendar.config import CalendarConfig
from app.calendar.models import (
    CalendarEvent, WorkflowDefinition, WorkflowResult, WorkflowStatus, WorkflowStep,
    WorkflowStepKind,
)
from app.calendar.service import CalendarService
from app.calendar.telemetry import emit_calendar_event

_MAX_RESULT_BYTES = 8192
_MAX_SUMMARY_CHARS = 2048


class StepRunner(Protocol):
    def run_step(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        ...


class CalendarStepRunner:
    """Default runner binding trusted, bounded calendar calls."""

    def __init__(self, service: CalendarService, announce: Any = None) -> None:
        self._service = service
        self._announce = announce

    def run_step(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
        kind = step.kind
        if kind is WorkflowStepKind.READ_SCHEDULE:
            day = context.get("_today")
            schedule = self._service.day_schedule(day)
            return {
                "events": len(schedule.events),
                "occurrences": len(schedule.occurrences),
                "conflicts": len(schedule.conflicts),
            }
        if kind is WorkflowStepKind.READ_DEADLINES:
            overdue = self._service.overdue_tasks()
            return {
                "overdue": len(overdue),
                "titles": [task.title for task in overdue
                           if task.status.value == "pending"][:8],
            }
        if kind is WorkflowStepKind.READ_UPCOMING:
            upcoming = self._service.upcoming(limit=8)
            return {
                "count": len(upcoming),
                "next": upcoming[0].title if upcoming else None,
            }
        if kind is WorkflowStepKind.ANNOUNCE:
            if self._announce is None:
                return {"announced": False}
            message = str(step.args.get("message", ""))[:512]
            self._announce(message)
            return {"announced": True}
        raise ValueError(f"unsupported workflow step kind: {kind}")


class _ConcurrencyGate:
    def __init__(self, slots: int) -> None:
        self._semaphore = threading.BoundedSemaphore(slots)

    def acquire(self) -> None:
        if not self._semaphore.acquire(timeout=0.5):
            raise _BusyError("workflow concurrency limit reached")

    def release(self) -> None:
        self._semaphore.release()


class _BusyError(Exception):
    pass


class WorkflowEngine:
    def __init__(self, config: CalendarConfig, bus: EventBus | None = None,
                 runner: StepRunner | None = None) -> None:
        self._config = config
        self._bus = bus
        self._runner = runner
        self._gate = _ConcurrencyGate(config.max_concurrent_workflows)

    def set_runner(self, runner: StepRunner) -> None:
        self._runner = runner

    def run(self, definition: WorkflowDefinition, *,
            context: dict[str, Any] | None = None,
            depth: int = 0, cancel: threading.Event | None = None,
            deadline: datetime | None = None,
            runner: StepRunner | None = None) -> WorkflowResult:
        started = datetime.now(timezone.utc)
        effective_runner = runner or self._runner
        if effective_runner is None:
            return WorkflowResult(workflow_id=definition.workflow_id,
                                  status=WorkflowStatus.FAILED,
                                  error_type="no_runner")
        if not definition.enabled:
            return WorkflowResult(workflow_id=definition.workflow_id,
                                  status=WorkflowStatus.CANCELLED,
                                  error_type="disabled")
        if depth >= self._config.max_workflow_depth:
            return WorkflowResult(workflow_id=definition.workflow_id,
                                  status=WorkflowStatus.FAILED,
                                  error_type="depth_exceeded")
        if not definition.steps:
            return WorkflowResult(workflow_id=definition.workflow_id,
                                  status=WorkflowStatus.COMPLETED,
                                  steps_executed=0,
                                  duration_ms=self._elapsed(started))

        self._gate.acquire()
        emit_calendar_event(self._bus, "WORKFLOW_EXECUTION_STARTED")
        try:
            budget = self._config.max_workflow_runtime_seconds
            effective_deadline = deadline or (started + timedelta(seconds=budget))
            steps_executed = 0
            summary_lines: list[str] = []
            step_context = dict(context or {})
            for step in definition.steps:
                if cancel is not None and cancel.is_set():
                    return WorkflowResult(workflow_id=definition.workflow_id,
                                          status=WorkflowStatus.CANCELLED,
                                          steps_executed=steps_executed,
                                          duration_ms=self._elapsed(started),
                                          error_type="cancelled")
                if datetime.now(timezone.utc) > effective_deadline:
                    return WorkflowResult(workflow_id=definition.workflow_id,
                                          status=WorkflowStatus.TIMED_OUT,
                                          steps_executed=steps_executed,
                                          duration_ms=self._elapsed(started),
                                          error_type="deadline")
                steps_executed += 1
                if steps_executed > self._config.max_workflow_steps:
                    return WorkflowResult(workflow_id=definition.workflow_id,
                                          status=WorkflowStatus.FAILED,
                                          steps_executed=steps_executed,
                                          duration_ms=self._elapsed(started),
                                          error_type="step_limit")
                if step.kind is WorkflowStepKind.NESTED:
                    nested = self._service_lookup(step)
                    if nested is None:
                        summary_lines.append(f"{step.key}: missing")
                        continue
                    nested_result = self.run(
                        nested, context=step_context, depth=depth + 1,
                        cancel=cancel, deadline=effective_deadline,
                        runner=effective_runner)
                    if nested_result.status is not WorkflowStatus.COMPLETED:
                        return nested_result
                    steps_executed += nested_result.steps_executed
                    if nested_result.summary:
                        summary_lines.append(nested_result.summary[:_MAX_SUMMARY_CHARS // len(nested_result.summary) + 1])
                    continue
                try:
                    output = effective_runner.run_step(step, step_context)
                except _BusyError:
                    return WorkflowResult(workflow_id=definition.workflow_id,
                                          status=WorkflowStatus.FAILED,
                                          steps_executed=steps_executed,
                                          duration_ms=self._elapsed(started),
                                          error_type="concurrency")
                except Exception:
                    return WorkflowResult(workflow_id=definition.workflow_id,
                                          status=WorkflowStatus.FAILED,
                                          steps_executed=steps_executed,
                                          duration_ms=self._elapsed(started),
                                          error_type="step_failed")
                step_key = step.key or step.kind.value
                for key, value in (output or {}).items():
                    text = self._short(value)
                    if text:
                        summary_lines.append(f"{step_key}.{key}={text}")
            return WorkflowResult(
                workflow_id=definition.workflow_id,
                status=WorkflowStatus.COMPLETED,
                steps_executed=steps_executed,
                duration_ms=self._elapsed(started),
                summary="\n".join(summary_lines)[:_MAX_SUMMARY_CHARS])
        finally:
            self._gate.release()
            emit_calendar_event(self._bus, "WORKFLOW_EXECUTION_COMPLETED",
                                success=True)

    def _service_lookup(self, step: WorkflowStep) -> WorkflowDefinition | None:
        from app.calendar.service import CalendarService
        if isinstance(self._runner, CalendarStepRunner):
            service: CalendarService = self._runner._service
            return service.get_workflow(step.target) if step.target else None
        return None

    @staticmethod
    def _elapsed(started: datetime) -> float:
        return (datetime.now(timezone.utc) - started).total_seconds() * 1000

    @staticmethod
    def _short(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)[:_MAX_RESULT_BYTES]
        if len(text.encode("utf-8")) > _MAX_RESULT_BYTES:
            text = text.encode("utf-8")[:_MAX_RESULT_BYTES].decode("utf-8", errors="ignore")
        return text