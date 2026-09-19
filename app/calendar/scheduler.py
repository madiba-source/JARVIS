"""Bounded reminder/trigger scheduler. No busy loops, idempotent firing."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from app.core.events import EventBus

from app.calendar.config import CalendarConfig
from app.calendar.service import CalendarService
from app.calendar.telemetry import emit_calendar_event
from app.calendar.workflows import WorkflowEngine


class CalendarScheduler:
    def __init__(self, service: CalendarService, config: CalendarConfig,
                 engine: WorkflowEngine | None = None,
                 bus: EventBus | None = None) -> None:
        self._service = service
        self._config = config
        self._engine = engine
        self._bus = bus
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._config.scheduler_enabled or not self._config.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="calendar-scheduler",
                                        daemon=True)
        self._thread.start()
        emit_calendar_event(self._bus, "CALENDAR_SCHEDULER_STARTED")

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None
        emit_calendar_event(self._bus, "CALENDAR_SCHEDULER_STOPPED")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._cycle()
            if self._stop.is_set():
                break
            try:
                self._stop.wait(timeout=self._config.scheduler_poll_max_seconds)
            except Exception:
                break

    def _cycle(self) -> None:
        """Process due reminders and triggers once. Deterministic and testable."""
        self._service.fire_due_reminders()
        if self._engine is not None:
            triggers = self._service.due_triggers()
            for trigger in triggers:
                if self._stop.is_set():
                    break
                try:
                    definition = self._service.get_workflow(str(trigger.workflow_id))
                except Exception:
                    continue
                if definition is None or not definition.enabled:
                    continue
                result = self._engine.run(definition, cancel=self._stop)
                if result.status.value in ("completed", "failed", "cancelled", "timed_out"):
                    now = datetime.now(timezone.utc)
                    self._service.store().mark_trigger_fired(str(trigger.trigger_id), now)
                    emit_calendar_event(
                        self._bus, "CALENDAR_TRIGGER_FIRED",
                        count=1,
                        extra={"status": result.status.value})

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def next_wake_delay(self) -> float:
        """Shortest delay until a pending item; bounded by poll max."""
        now = datetime.now(timezone.utc)
        due = self._service.pending_reminders(due_before=None)
        candidates: list[datetime] = []
        for reminder in due:
            if reminder.status.value == "pending":
                candidates.append(reminder.remind_at)
        for trigger in self._service.triggers(enabled_only=True):
            if trigger.trigger_type.value == "at_time" and trigger.at_time is not None:
                wall = datetime.combine(now.astimezone(self._service.timezone).date(),
                                        trigger.at_time,
                                        tzinfo=self._service.timezone)
                if wall > now:
                    candidates.append(wall)
        if not candidates:
            return self._config.scheduler_poll_max_seconds
        delay = (min(candidates) - now).total_seconds()
        return max(0.1, min(float(delay), self._config.scheduler_poll_max_seconds))

    # -- arrow-style iteration bound helper used by tests --
    _cycle_budget = 256