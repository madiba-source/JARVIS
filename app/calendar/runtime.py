"""Explicit calendar runtime composition; failure leaves a usable disabled state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.events import EventBus
from app.database.config import DatabaseConfig
from app.database.service import DatabaseService
from app.memory.migration import MEMORY_MIGRATIONS

from app.calendar.capabilities import CalendarPolicyService
from app.calendar.clock import CalendarClock, SystemClock, make_tz
from app.calendar.config import CalendarConfig
from app.calendar.migration import CALENDAR_MIGRATIONS
from app.calendar.scheduler import CalendarScheduler
from app.calendar.service import CalendarService
from app.calendar.store import CalendarStore
from app.calendar.telemetry import emit_calendar_event
from app.calendar.timetable import TimetablePlanner
from app.calendar.workflows import CalendarStepRunner, WorkflowEngine
from app.proactive.migration import PROACTIVE_MIGRATIONS

_SHARED_MIGRATIONS = MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS + PROACTIVE_MIGRATIONS


class CalendarRuntime:
    def __init__(self, data_dir: Path, config: CalendarConfig, bus: EventBus,
                 database: DatabaseService | None = None,
                 clock: CalendarClock | None = None,
                 announce: Any = None) -> None:
        self.service: CalendarService | None = None
        self.planner: TimetablePlanner | None = None
        self.workflow_engine: WorkflowEngine | None = None
        self.policy: CalendarPolicyService | None = None
        self.scheduler: CalendarScheduler | None = None
        self.available = False
        try:
            if database is None:
                database = DatabaseService(
                    DatabaseConfig(db_path=str(data_dir / "jarvis.db"),
                                   backup_directory=str(data_dir / "backups")),
                    extension_migrations=_SHARED_MIGRATIONS,
                )
            database.initialize()
            self.timezone = make_tz(config.timezone)
            self.service = CalendarService(CalendarStore(database, config), config,
                                           clock=clock or SystemClock(), bus=bus)
            self.planner = TimetablePlanner(self.service, config)
            self.workflow_engine = WorkflowEngine(
                config, bus, runner=CalendarStepRunner(self.service, announce))
            self.policy = CalendarPolicyService(self.service, config, bus)
            self.scheduler = CalendarScheduler(self.service, config,
                                               self.workflow_engine, bus)
            self.available = True
            emit_calendar_event(bus, "CALENDAR_ENABLED")
            if config.enabled and config.scheduler_enabled:
                self.scheduler.start()
        except Exception:
            self.available = False
            self.service = None
            emit_calendar_event(bus, "CALENDAR_UNAVAILABLE", success=False,
                                error_type="startup")

    def close(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop()
        self.available = False