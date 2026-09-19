"""Calendar domain service: validated reads and mutations over the store."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.events import EventBus

from app.calendar.clock import CalendarClock, SystemClock, make_tz
from app.calendar.config import CalendarConfig
from app.calendar.conflicts import detect_conflicts, free_time, merge_intervals, overlaps
from app.calendar.models import (
    CalendarEvent, CalendarQuery, CalendarRecurrence, CalendarReminder, CalendarTask,
    ConflictKind, DaySchedule, EventStatus, QueryKind, ReminderStatus, ReminderTargetKind,
    ScheduleConflict, ScheduleOccurrence, Subject, TaskPriority, TaskStatus, TimeRange,
    TimetableEntry, WeekSchedule, Weekday, WorkflowDefinition, WorkflowResult, WorkflowStatus,
    WorkflowStep, WorkflowTrigger, weekday_of,
)
from app.calendar.store import CalendarStore
from app.calendar.telemetry import emit_calendar_event
from app.calendar.transfer import export_ics, import_ics


class CalendarError(ValueError):
    pass


class EventNotFound(CalendarError):
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"event not found: {event_id!r}")


class TaskNotFound(CalendarError):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"task not found: {task_id!r}")


class RecurrenceNotFound(CalendarError):
    def __init__(self, recurrence_id: str) -> None:
        self.recurrence_id = recurrence_id
        super().__init__(f"recurrence not found: {recurrence_id!r}")


class ConflictRejected(CalendarError):
    def __init__(self, conflicts: list[ScheduleConflict]) -> None:
        self.conflicts = conflicts
        super().__init__("schedule conflict rejected")


class CalendarService:
    def __init__(self, store: CalendarStore, config: CalendarConfig,
                 clock: CalendarClock | None = None, bus: EventBus | None = None) -> None:
        self._store = store
        self._config = config
        self._clock = clock or SystemClock()
        self._bus = bus

    @property
    def timezone(self) -> ZoneInfo:
        return make_tz(self._config.timezone)

    @property
    def clock(self) -> CalendarClock:
        return self._clock

    # ---- helpers ----

    def _emit(self, event_type: str, *, success: bool = True, count: int = 0,
              error_type: str = "", duration_ms: float | None = None,
              extra: dict[str, Any] | None = None) -> None:
        emit_calendar_event(self._bus, event_type, success=success,
                            error_type=error_type, count=count,
                            duration_ms=duration_ms, extra=extra)

    def _now(self) -> datetime:
        return self._clock.now()

    # ---- events ----

    def create_event(self, *, title: str, start: datetime | None = None,
                     end: datetime | None = None, start_date: date | None = None,
                     end_date: date | None = None, all_day: bool = False,
                     description: str = "", kind: str = "event",
                     recurrence: CalendarRecurrence | None = None,
                     timezone: str | None = None,
                     check_conflicts: bool = True,
                     source: str = "calendar") -> CalendarEvent:
        zone = self.timezone
        event = CalendarEvent(
            title=title, description=description, kind=kind,
            all_day=all_day, start=start, end=end,
            start_date=start_date, end_date=end_date,
            timezone=(timezone or self._config.timezone),
            source=source, created_at=self._now(), updated_at=self._now())
        if recurrence is not None:
            event = event.model_copy(update={"recurrence_id": recurrence.recurrence_id})
        if check_conflicts and not all_day:
            conflicts = self._event_conflicts(event)
            if conflicts:
                self._emit("CALENDAR_MUTATION_DENIED", success=False,
                           error_type="conflict")
                raise ConflictRejected(conflicts)
        self._store.insert_event(event, event.model_dump_json())
        if recurrence is not None:
            self._store.insert_recurrence(recurrence)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "create_event"})
        return event

    def _apply_recurrence(self, event: CalendarEvent,
                          recurrence: CalendarRecurrence | None) -> None:
        if recurrence is None:
            return
        event.model_copy(update={"recurrence_id": recurrence.recurrence_id})

    def get_event(self, event_id: str) -> CalendarEvent | None:
        return self._store.get_event(str(event_id))

    def update_event(self, event_id: str, *, title: str | None = None,
                     description: str | None = None, start: datetime | None = None,
                     end: datetime | None = None, start_date: date | None = None,
                     end_date: date | None = None,
                     all_day: bool | None = None,
                     check_conflicts: bool = True,
                     source: str = "calendar") -> CalendarEvent:
        existing = self._require_event(event_id)
        now = self._now()
        updated = existing.model_copy(update={"updated_at": now, "source": source})
        if title is not None:
            updated = updated.model_copy(update={"title": title})
        if description is not None:
            updated = updated.model_copy(update={"description": description})
        if all_day is not None:
            updated = updated.model_copy(update={"all_day": all_day})
        if start is not None:
            updated = updated.model_copy(update={"start": start, "start_date": None})
        if end is not None:
            updated = updated.model_copy(update={"end": end, "end_date": None})
        if start_date is not None:
            updated = updated.model_copy(update={"start_date": start_date, "start": None})
        if end_date is not None:
            updated = updated.model_copy(update={"end_date": end_date, "end": None})
        updated = updated.model_copy(update={"version": existing.version + 1})
        updated = CalendarEvent.model_validate(updated.model_copy(update={}).model_dump())
        if check_conflicts and not updated.all_day:
            conflicts = self._event_conflicts(updated)
            if conflicts:
                self._emit("CALENDAR_MUTATION_DENIED", success=False, error_type="conflict")
                raise ConflictRejected(conflicts)
        self._store.update_event(updated, updated.model_dump_json())
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "update_event"})
        return updated

    def move_event(self, event_id: str, *, to_start: datetime, check_conflicts: bool = True) -> CalendarEvent:
        existing = self._require_event(event_id)
        if existing.all_day:
            updated = existing.model_copy(update={"start_date": to_start.date(),
                                                  "end_date": to_start.date(),
                                                  "updated_at": self._now()})
        else:
            duration = existing.end - existing.start if existing.end else timedelta(hours=1)
            updated = existing.model_copy(update={"start": to_start,
                                                  "end": to_start + duration,
                                                  "updated_at": self._now()})
        if check_conflicts and not updated.all_day:
            conflicts = self._event_conflicts(updated)
            if conflicts:
                self._emit("CALENDAR_MUTATION_DENIED", success=False, error_type="conflict")
                raise ConflictRejected(conflicts)
        self._store.update_event(updated, updated.model_dump_json())
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "move_event"})
        return updated

    def resize_event(self, event_id: str, *, duration_minutes: int, check_conflicts: bool = True) -> CalendarEvent:
        existing = self._require_event(event_id)
        if existing.all_day:
            raise CalendarError("cannot resize an all-day event")
        if not 1 <= duration_minutes <= 24 * 60:
            raise CalendarError("duration out of range")
        updated = existing.model_copy(update={
            "end": existing.start + timedelta(minutes=duration_minutes),
            "updated_at": self._now()})
        conflicts = self._event_conflicts(updated)
        if conflicts:
            self._emit("CALENDAR_MUTATION_DENIED", success=False, error_type="conflict")
            raise ConflictRejected(conflicts)
        self._store.update_event(updated, updated.model_dump_json())
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "resize_event"})
        return updated

    def cancel_event(self, event_id: str) -> CalendarEvent:
        existing = self._require_event(event_id)
        updated = existing.model_copy(update={"status": EventStatus.CANCELLED,
                                              "updated_at": self._now()})
        self._store.update_event(updated, updated.model_dump_json())
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "cancel_event"})
        return updated

    def delete_event(self, event_id: str) -> None:
        self._require_event(event_id)
        self._store.delete_event(str(event_id))
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "delete_event"})

    def _require_event(self, event_id: str) -> CalendarEvent:
        event = self._store.get_event(str(event_id))
        if event is None:
            raise EventNotFound(str(event_id))
        return event

    def _event_conflicts(self, candidate: CalendarEvent) -> list[ScheduleConflict]:
        if candidate.all_day:
            return []
        if candidate.start is None or candidate.end is None:
            return []
        if candidate.status is EventStatus.CANCELLED:
            return []
        conflicts: list[ScheduleConflict] = []
        for other in self._store.events_in_range(candidate.start, candidate.end):
            if other.event_id == candidate.event_id:
                continue
            if other.status is EventStatus.CANCELLED or other.all_day:
                continue
            trange = other.as_time_range()
            if trange is not None and trange.overlaps(TimeRange(start=candidate.start, end=candidate.end)):
                conflicts.append(ScheduleConflict(
                    kind=ConflictKind.EVENT_EVENT,
                    start=max(candidate.start, trange.start),
                    end=min(candidate.end, trange.end),
                    parties=(str(candidate.event_id), str(other.event_id))))
        return conflicts

    def recurring_occurrences(self, event_id: str, *, limit: int | None = None) -> list[CalendarEvent]:
        event = self._require_event(event_id)
        if event.recurrence_id is None:
            return [event]
        rule = self._store.get_recurrence(str(event.recurrence_id))
        if rule is None:
            return [event]
        from app.calendar.recurrence import expand
        maximum = min(limit or self._config.max_occurrences_per_query,
                      self._config.max_occurrences_per_query)
        occurrences = expand(rule, max_occurrences=maximum,
                             horizon_days=self._config.max_recurrence_horizon_days)
        results = []
        for occurrence in occurrences:
            copy = event.model_copy(update={
                "start": occurrence, "end": occurrence + timedelta(hours=1),
                "all_day": False, "start_date": None, "end_date": None,
                "updated_at": self._now()})
            results.append(copy)
        return results[:maximum]

    # ---- queries ----

    def query(self, query: CalendarQuery) -> dict[str, Any]:
        if query.kind is QueryKind.DAY:
            return self.day_schedule(query.date, timezone=self._config.timezone).model_dump(mode="json")
        if query.kind is QueryKind.WEEK:
            week = self.week_schedule(query.date, timezone=self._config.timezone)
            return week.model_dump(mode="json")
        if query.kind is QueryKind.RANGE:
            return {"events": [event.model_dump(mode="json") for event in self.list_events(
                since=query.start, until=query.end, limit=query.limit)]}
        if query.kind is QueryKind.UPCOMING:
            return {"events": [event.model_dump(mode="json") for event in self.upcoming(
                query.limit)]}
        if query.kind is QueryKind.TASKS:
            return {"tasks": [task.model_dump(mode="json") for task in self.tasks(
                status=None, limit=query.limit, project=query.project, subject=query.subject)]}
        if query.kind is QueryKind.TASKS_OVERDUE:
            return {"tasks": [task.model_dump(mode="json") for task in self.overdue_tasks(
                limit=query.limit)]}
        if query.kind is QueryKind.FREE_TIME:
            if query.start is None or query.end is None:
                raise CalendarError("free-time query requires start and end")
            slots = self.find_free_time(query.start, query.end,
                                        query.minimum_duration_minutes)
            return {"slots": [slot.model_dump(mode="json") for slot in slots]}
        if query.kind is QueryKind.NEXT_OCCURRENCE:
            after = query.start or (self._now() if query.date is None
                                    else datetime.combine(query.date, time.min, tzinfo=self.timezone))
            return (self.next_event(after) or CalendarEvent(
                title="(none)", all_day=False, start=self._now(), end=self._now() + timedelta(hours=1))).model_dump(mode="json")
        if query.kind is QueryKind.NEXT_CLASS:
            return (self.next_class(query.start) or ScheduleOccurrence(
                entry_id=uuid.uuid4(), subject="(none)", date=self._clock.today(self.timezone),
                start=self._now(), end=self._now() + timedelta(hours=1))).model_dump(mode="json")
        raise CalendarError(f"unsupported query kind: {query.kind}")

    def day_schedule(self, day: date, *, timezone: str | None = None) -> DaySchedule:
        zone = make_tz(timezone or self._config.timezone)
        start = datetime.combine(day, time.min, tzinfo=zone)
        end = start + timedelta(days=1)
        events = tuple(self._store.events_in_range(start, end))
        occurrences = tuple(self._store.occurrences_for_date(day, tz=zone))
        tasks = tuple(task for task in self._store.list_tasks()
                      if task.due_at and start <= task.due_at < end)
        conflicts = self._conflicts_for(events, occurrences)
        return DaySchedule(date=day, timezone=zone.key, events=events,
                           occurrences=occurrences, tasks=tasks, conflicts=conflicts)

    def week_schedule(self, day: date | None = None, *, timezone: str | None = None) -> WeekSchedule:
        zone = make_tz(timezone or self._config.timezone)
        reference = day or self._clock.today(zone)
        monday = reference - timedelta(days=reference.weekday())
        days = tuple(self.day_schedule(monday + timedelta(days=offset), timezone=zone.key)
                     for offset in range(7))
        return WeekSchedule(start_date=monday, end_date=monday + timedelta(days=6),
                            timezone=zone.key, days=days)

    def list_events(self, *, since: datetime | None = None,
                    until: datetime | None = None,
                    limit: int | None = None) -> list[CalendarEvent]:
        return self._store.list_events(since=since, until=until, limit=limit)

    def upcoming(self, limit: int | None = None) -> list[CalendarEvent]:
        now = self._now()
        window = now + timedelta(days=30)
        return [event for event in self._store.events_in_range(now, window)
                if event.status is not EventStatus.CANCELLED][: (limit or self._config.max_events_returned)]

    def next_event(self, after: datetime | None = None) -> CalendarEvent | None:
        cutoff = after or self._now()
        candidates = [event for event in self._store.events_in_range(cutoff, cutoff + timedelta(days=366))
                      if event.status is not EventStatus.CANCELLED and not event.all_day
                      and event.start is not None and event.start >= cutoff]
        if not candidates:
            return None
        candidates.sort(key=lambda event: event.start)
        return candidates[0]

    def next_class(self, after: datetime | None = None) -> ScheduleOccurrence | None:
        cutoff = after or self._now()
        zone = self.timezone
        tomorrow = (cutoff + timedelta(days=2)).date()
        occurrences: list[ScheduleOccurrence] = []
        for day in [cutoff.date(), cutoff.date() + timedelta(days=1), tomorrow]:
            for occurrence in self._store.occurrences_for_date(day, tz=zone):
                if occurrence.start > cutoff:
                    occurrences.append(occurrence)
        if not occurrences:
            return None
        occurrences.sort(key=lambda item: item.start)
        return occurrences[0]

    def _conflicts_for(self, events: list[CalendarEvent],
                       occurrences: list[ScheduleOccurrence]) -> tuple[ScheduleConflict, ...]:
        conflicts = self._event_conflict_pairs(events)
        for event in events:
            if event.all_day or event.status is EventStatus.CANCELLED or event.start is None or event.end is None:
                continue
            event_range = TimeRange(start=event.start, end=event.end)
            for occurrence in occurrences:
                occurrence_range = TimeRange(start=occurrence.start, end=occurrence.end)
                if event_range.overlaps(occurrence_range):
                    conflicts.append(ScheduleConflict(
                        kind=ConflictKind.EVENT_TIMETABLE,
                        start=max(event_range.start, occurrence_range.start),
                        end=min(event_range.end, occurrence_range.end),
                        parties=(str(event.event_id), str(occurrence.entry_id))))
        entry_pairs = detect_conflicts(
            [TimeRange(start=occ.start, end=occ.end) for occ in occurrences],
            [str(occ.entry_id) for occ in occurrences],
            ConflictKind.TIMETABLE_TIMETABLE)
        conflicts.extend(entry_pairs)
        conflicts.sort(key=lambda item: item.start)
        return tuple(conflicts[:256])

    def _event_conflict_pairs(self, events: list[CalendarEvent]) -> list[ScheduleConflict]:
        conflicts: list[ScheduleConflict] = []
        timed = [(event, event.as_time_range(self.timezone)) for event in events
                 if not event.all_day and event.status is not EventStatus.CANCELLED
                 and event.as_time_range(self.timezone) is not None]
        pairs = [(left, right) for left, right in zip(timed[:-1], timed[1:])]
        intervals = [item[1] for item in timed]
        parties = [str(item[0].event_id) for item in timed]
        return detect_conflicts(intervals, parties, ConflictKind.EVENT_EVENT)

    # ---- tasks ----

    def create_task(self, *, title: str, description: str = "", due_at: datetime | None = None,
                    priority: str = "medium", subject: str = "", project: str = "",
                    tags: tuple[str, ...] = (), source: str = "calendar") -> CalendarTask:
        task = CalendarTask(title=title, description=description, due_at=due_at,
                            priority=priority, subject=subject, project=project,
                            tags=tags, created_at=self._now())
        self._store.insert_task(task)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "create_task"})
        return task

    def tasks(self, *, status: TaskStatus | None = None, limit: int | None = None,
              project: str = "", subject: str = "") -> list[CalendarTask]:
        return self._store.list_tasks(status=status, limit=limit,
                                      project=project, subject=subject)

    def get_task(self, task_id: str) -> CalendarTask | None:
        return self._store.get_task(str(task_id))

    def _require_task(self, task_id: str) -> CalendarTask:
        task = self._store.get_task(str(task_id))
        if task is None:
            raise TaskNotFound(str(task_id))
        return task

    def overdue_tasks(self, *, limit: int | None = None) -> list[CalendarTask]:
        return self._store.list_tasks(overdue_since=self._now(), limit=limit)

    def complete_task(self, task_id: str) -> CalendarTask:
        existing = self._require_task(task_id)
        updated = existing.model_copy(update={"status": TaskStatus.COMPLETED,
                                              "completed_at": self._now()})
        self._store.update_task(updated)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "complete_task"})
        return updated

    def postpone_task(self, task_id: str, *, to: datetime) -> CalendarTask:
        existing = self._require_task(task_id)
        updated = existing.model_copy(update={"due_at": to})
        self._store.update_task(updated)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "postpone_task"})
        return updated

    def delete_task(self, task_id: str) -> None:
        self._require_task(task_id)
        self._store.delete_task(str(task_id))
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "delete_task"})

    # ---- reminders ----

    def create_reminder(self, *, target_id: str | UUID, target_kind: str,
                        remind_at: datetime, notification_type: str = "announce") -> CalendarReminder:
        reminder = CalendarReminder(target_id=UUID(str(target_id)), target_kind=target_kind,
                                    remind_at=remind_at,
                                    notification_type=notification_type,
                                    created_at=self._now())
        self._store.insert_reminder(reminder)
        self._emit("CALENDAR_REMINDER_SCHEDULED", count=1)
        return reminder

    def pending_reminders(self, *, limit: int | None = None,
                          due_before: datetime | None = None) -> list[CalendarReminder]:
        return self._store.get_reminders(status=ReminderStatus.PENDING,
                                         due_before=due_before or self._now(),
                                         limit=limit or self._config.max_reminders_per_cycle)

    def cancel_reminder(self, reminder_id: str) -> CalendarReminder:
        reminders = self._store.get_reminders(status=None, due_before=None)
        match = next((item for item in reminders if str(item.reminder_id) == str(reminder_id)), None)
        if match is None:
            raise CalendarError("reminder not found")
        updated = match.model_copy(update={"status": ReminderStatus.CANCELLED})
        self._store.update_reminder(updated)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "cancel_reminder"})
        return updated

    def fire_due_reminders(self, *, now: datetime | None = None,
                           limit: int | None = None) -> list[CalendarReminder]:
        cutoff = now or self._now()
        due = self._store.get_reminders(status=ReminderStatus.PENDING,
                                        due_before=cutoff,
                                        limit=limit or self._config.max_reminders_per_cycle)
        fired: list[CalendarReminder] = []
        for reminder in due:
            self._store.fire_reminder(str(reminder.reminder_id), cutoff)
            fired.append(reminder.model_copy(update={"status": ReminderStatus.FIRED,
                                                     "fired_at": cutoff}))
        if fired:
            self._emit("CALENDAR_REMINDER_FIRED", count=len(fired))
        return fired

    # ---- subjects ----

    def upsert_subject(self, *, name: str, category: str = "") -> Subject:
        subject = Subject(name=name, category=category)
        self._store.upsert_subject(subject)
        return subject

    def subjects(self, limit: int = 128) -> list[Subject]:
        return self._store.list_subjects(limit)

    # ---- timetable ----

    def create_timetable_entry(self, *, subject: str, teacher: str = "",
                               room: str = "", weekday: str, start_time: time,
                               end_time: time, term: str = "",
                               notes: str = "") -> TimetableEntry:
        entry = TimetableEntry(subject=subject, teacher=teacher, room=room,
                               weekday=weekday, start_time=start_time,
                               end_time=end_time, term=term, notes=notes)
        self._store.insert_timetable(entry)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "create_timetable_entry"})
        return entry

    def update_timetable_entry(self, entry_id: str, **fields) -> TimetableEntry:
        existing = self.timetable_entry(str(entry_id))
        updated = existing.model_copy(update={**fields})
        updated = TimetableEntry.model_validate(updated.model_dump())
        self._store.update_timetable(updated)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "update_timetable_entry"})
        return updated

    def delete_timetable_entry(self, entry_id: str) -> None:
        self.timetable_entry(str(entry_id))
        self._store.delete_timetable_entry(str(entry_id))
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "delete_timetable_entry"})

    def timetable(self, *, weekday: Weekday | str | None = None, term: str = "",
                  limit: int = 256) -> list[TimetableEntry]:
        if isinstance(weekday, str) and weekday:
            weekday = Weekday(weekday)
        return self._store.list_timetable(weekday=weekday, term=term, limit=limit)

    def timetable_entry(self, entry_id: str) -> TimetableEntry:
        entry = self._store.get_timetable_entry(str(entry_id))
        if entry is None:
            raise CalendarError("timetable entry not found")
        return entry

    # ---- free time ----

    def find_free_time(self, start: datetime, end: datetime,
                       minimum_duration_minutes: int = 0) -> list[TimeRange]:
        window = TimeRange(start=start, end=end)
        busy: list[TimeRange] = []
        for event in self._store.events_in_range(start, end):
            if event.all_day or event.status is EventStatus.CANCELLED:
                continue
            trange = event.as_time_range(self.timezone)
            if trange is None:
                continue
            if overlaps(trange, window):
                busy.append(TimeRange(start=max(trange.start, window.start),
                                      end=min(trange.end, window.end)))
        for occurrence in self._store.occurrences_for_date(window.start.date(), tz=self.timezone):
            ocr = TimeRange(start=occurrence.start, end=occurrence.end)
            if overlaps(ocr, window):
                busy.append(TimeRange(start=max(ocr.start, window.start), end=min(ocr.end, window.end)))
        merged = merge_intervals(busy)
        return free_time(merged, window, minimum_duration_minutes)

    # ---- workflows ----

    def save_workflow(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        if definition.step_count > self._config.max_workflow_steps:
            raise CalendarError("workflow exceeds step limit")
        self._store.upsert_workflow(definition)
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "save_workflow"})
        return definition

    def run_workflow(self, definition: WorkflowDefinition,
                     *, engine=None, cancel=None) -> WorkflowResult:
        from app.calendar.workflows import CalendarStepRunner, WorkflowEngine
        runner_engine = engine or WorkflowEngine(self._config, self._bus)
        runner_engine.set_runner(CalendarStepRunner(self, announce=None))
        return runner_engine.run(definition, cancel=cancel)

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._store.get_workflow(str(workflow_id))

    def workflows(self, *, enabled_only: bool = False) -> list[WorkflowDefinition]:
        return self._store.list_workflows(enabled_only=enabled_only)

    def delete_workflow(self, workflow_id: str) -> None:
        self._store.delete_workflow(str(workflow_id))
        self._emit("CALENDAR_MUTATION_COMPLETED", count=1,
                   extra={"operation": "delete_workflow"})

    def save_trigger(self, trigger: WorkflowTrigger) -> WorkflowTrigger:
        if self.get_workflow(str(trigger.workflow_id)) is None:
            raise CalendarError("workflow not found for trigger")
        self._store.upsert_trigger(trigger)
        return trigger

    def triggers(self, *, enabled_only: bool = False) -> list[WorkflowTrigger]:
        return self._store.list_triggers(enabled_only=enabled_only)

    def delete_trigger(self, trigger_id: str) -> None:
        self._store.delete_trigger(str(trigger_id))

    def due_triggers(self, *, now: datetime | None = None) -> list[WorkflowTrigger]:
        cutoff = now or self._now()
        zone = self.timezone
        due: list[WorkflowTrigger] = []
        for trigger in self._store.list_triggers(enabled_only=True):
            if trigger.trigger_type.value == "at_time" and trigger.at_time is not None:
                wall = datetime.combine(cutoff.astimezone(zone).date(), trigger.at_time, tzinfo=zone)
                if wall.astimezone(zone) <= cutoff and (trigger.last_fired_at is None
                                                        or wall.astimezone(zone) > trigger.last_fired_at.astimezone(zone)):
                    due.append(trigger)
        return due

    def store(self) -> CalendarStore:
        return self._store

    def export_ics(self) -> bytes:
        return export_ics(self.list_events(limit=self._config.max_ics_events), self._config)

    def import_ics(self, payload: bytes) -> list[CalendarEvent]:
        imported = import_ics(payload, self._config)
        for event in imported:
            self.create_event(title=event.title, description=event.description,
                              start=event.start, end=event.end, source="icalendar")
        return imported