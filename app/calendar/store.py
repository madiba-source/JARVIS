"""SQLite persistence for the calendar subsystem. Parameterized SQL only."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.database.service import DatabaseService

from app.calendar.config import CalendarConfig
from app.calendar.models import (
    CalendarEvent, CalendarRecurrence, CalendarReminder, CalendarTask,
    RecurrenceFreq, ReminderStatus, ScheduleOccurrence, Subject,
    TaskStatus, TimetableEntry, Weekday, WorkflowDefinition, WorkflowTrigger,
    weekday_index,
)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class CalendarStore:
    """Trusted internal persistence; exposed only through CalendarService."""

    def __init__(self, database: DatabaseService, config: CalendarConfig) -> None:
        self._db = database
        self._config = config

    # ---- events ----

    def insert_event(self, event: CalendarEvent, version_record: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO calendar_events
                   (event_id, title, description, kind, all_day,
                    start, end, start_date, end_date, tz, recurrence_id,
                    status, source, created_at, updated_at, version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(event.event_id), event.title, event.description, event.kind.value,
                 int(event.all_day),
                 event.start.isoformat() if event.start else None,
                 event.end.isoformat() if event.end else None,
                 event.start_date.isoformat() if event.start_date else None,
                 event.end_date.isoformat() if event.end_date else None,
                 event.timezone, str(event.recurrence_id) if event.recurrence_id else None,
                 event.status.value, event.source,
                 event.created_at.isoformat(), event.updated_at.isoformat(),
                 event.version))
            conn.execute(
                "INSERT INTO calendar_event_versions(event_id,version,record) VALUES(?,?,?)",
                (str(event.event_id), event.version, version_record))

    def update_event(self, event: CalendarEvent, version_record: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """UPDATE calendar_events
                   SET title=?, description=?, kind=?, all_day=?,
                       start=?, end=?, start_date=?, end_date=?, tz=?,
                       recurrence_id=?, status=?, source=?, updated_at=?, version=?
                   WHERE event_id=?""",
                (event.title, event.description, event.kind.value, int(event.all_day),
                 event.start.isoformat() if event.start else None,
                 event.end.isoformat() if event.end else None,
                 event.start_date.isoformat() if event.start_date else None,
                 event.end_date.isoformat() if event.end_date else None,
                 event.timezone,
                 str(event.recurrence_id) if event.recurrence_id else None,
                 event.status.value, event.source,
                 event.updated_at.isoformat(), event.version, str(event.event_id)))
            conn.execute(
                "INSERT INTO calendar_event_versions(event_id,version,record) VALUES(?,?,?)",
                (str(event.event_id), event.version, version_record))

    def get_event(self, event_id: str) -> CalendarEvent | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_events WHERE event_id=?",
                (event_id,)).fetchone()
        return self._event_from_row(row) if row else None

    def delete_event(self, event_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM calendar_event_versions WHERE event_id=?", (event_id,))
            conn.execute("DELETE FROM calendar_events WHERE event_id=?", (event_id,))
            conn.execute("DELETE FROM calendar_reminders WHERE target_id=? AND target_kind='event'",
                         (event_id,))

    def list_events(self, *, since: datetime | None = None, until: datetime | None = None,
                    limit: int | None = None) -> list[CalendarEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("(all_day = 0 AND start >= ? OR all_day = 1 AND start_date >= ?)")
            params.append(_dt(until.isoformat()) if False else since.isoformat())
            params.append(since.date().isoformat())
        if until is not None:
            clauses.append("(all_day = 0 AND start < ? OR all_day = 1 AND start_date < ?)")
            params.append(until.isoformat())
            params.append(until.date().isoformat())
        limit = limit or self._config.max_events_returned
        sql = "SELECT * FROM calendar_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(start, start_date || ' 00:00:00') LIMIT ?"
        params.append(limit)
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._event_from_row(row) for row in rows]

    def events_in_range(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                """SELECT * FROM calendar_events
                         WHERE (all_day = 0 AND start < ? AND end > ?)
                             OR (all_day = 1 AND start_date <= ? AND end_date >= ?)
                   ORDER BY COALESCE(start, start_date || ' 00:00:00')
                   LIMIT ?""",
                     (end.isoformat(), start.isoformat(),
                      end.date().isoformat(), start.date().isoformat(),
                 self._config.max_events_returned * 4)).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _event_from_row(self, row) -> CalendarEvent:
        return CalendarEvent(
            event_id=row["event_id"], title=row["title"], description=row["description"],
            kind=row["kind"], all_day=bool(row["all_day"]),
            start=_dt(row["start"]), end=_dt(row["end"]),
            start_date=_day(row["start_date"]), end_date=_day(row["end_date"]),
            timezone=row["tz"], recurrence_id=row["recurrence_id"],
            status=row["status"], source=row["source"],
            created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]),
            version=row["version"])

    # ---- recurrences ----

    def insert_recurrence(self, rule: CalendarRecurrence) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO calendar_recurrences
                   (recurrence_id, freq, interval, by_day, by_month_day, count,
                    until, dtstart, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(rule.recurrence_id), rule.freq.value, rule.interval,
                 json.dumps([day.value for day in rule.by_day]),
                 rule.by_month_day, rule.count,
                 rule.until.isoformat() if rule.until else None,
                 rule.dtstart.isoformat(), rule.created_at.isoformat()))

    def get_recurrence(self, recurrence_id: str) -> CalendarRecurrence | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_recurrences WHERE recurrence_id=?",
                (recurrence_id,)).fetchone()
        if not row:
            return None
        return CalendarRecurrence(
            recurrence_id=row["recurrence_id"], freq=row["freq"],
            interval=row["interval"],
            by_day=tuple(Weekday(item) for item in json.loads(row["by_day"])),
            by_month_day=row["by_month_day"], count=row["count"],
            until=_dt(row["until"]), dtstart=_dt(row["dtstart"]),
            created_at=_dt(row["created_at"]))

    def delete_recurrence(self, recurrence_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM calendar_recurrences WHERE recurrence_id=?",
                         (recurrence_id,))

    # ---- reminders ----

    def insert_reminder(self, reminder: CalendarReminder) -> None:
        self._upsert_reminder(reminder)

    def update_reminder(self, reminder: CalendarReminder) -> None:
        self._upsert_reminder(reminder)

    def _upsert_reminder(self, reminder: CalendarReminder) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO calendar_reminders
                   (reminder_id, target_id, target_kind, remind_at, notification_type,
                    status, created_at, fired_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(reminder_id) DO UPDATE SET
                     target_id=excluded.target_id, target_kind=excluded.target_kind,
                     remind_at=excluded.remind_at,
                     notification_type=excluded.notification_type,
                     status=excluded.status, fired_at=excluded.fired_at""",
                (str(reminder.reminder_id), str(reminder.target_id),
                 reminder.target_kind.value, reminder.remind_at.isoformat(),
                 reminder.notification_type, reminder.status.value,
                 reminder.created_at.isoformat(), reminder.fired_at.isoformat() if reminder.fired_at else None))

    def get_reminders(self, *, status: ReminderStatus | None = None,
                      due_before: datetime | None = None,
                      limit: int | None = None) -> list[CalendarReminder]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if due_before is not None:
            clauses.append("remind_at <= ?")
            params.append(due_before.isoformat())
        limit = limit or self._config.max_reminders_per_cycle
        sql = "SELECT * FROM calendar_reminders"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY remind_at LIMIT ?"
        params.append(limit)
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def _reminder_from_row(self, row) -> CalendarReminder:
        return CalendarReminder(
            reminder_id=row["reminder_id"], target_id=row["target_id"],
            target_kind=row["target_kind"], remind_at=_dt(row["remind_at"]),
            notification_type=row["notification_type"], status=row["status"],
            created_at=_dt(row["created_at"]), fired_at=_dt(row["fired_at"]))

    def fire_reminder(self, reminder_id: str, fired_at: datetime) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """UPDATE calendar_reminders SET status='fired', fired_at=?
                   WHERE reminder_id=? AND status='pending'""",
                (fired_at.isoformat(), reminder_id))

    def delete_reminder(self, reminder_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM calendar_reminders WHERE reminder_id=?",
                         (reminder_id,))

    # ---- tasks ----

    def insert_task(self, task: CalendarTask) -> None:
        self._upsert_task(task)

    def update_task(self, task: CalendarTask) -> None:
        self._upsert_task(task)

    def _upsert_task(self, task: CalendarTask) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO calendar_tasks
                   (task_id, title, description, due_at, priority, status,
                    created_at, completed_at, subject, project, tags)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                     title=excluded.title, description=excluded.description,
                     due_at=excluded.due_at, priority=excluded.priority,
                     status=excluded.status, completed_at=excluded.completed_at,
                     subject=excluded.subject, project=excluded.project,
                     tags=excluded.tags""",
                (str(task.task_id), task.title, task.description,
                 task.due_at.isoformat() if task.due_at else None,
                 task.priority.value, task.status.value,
                 task.created_at.isoformat(),
                 task.completed_at.isoformat() if task.completed_at else None,
                 task.subject, task.project,
                 json.dumps(list(task.tags))))

    def get_task(self, task_id: str) -> CalendarTask | None:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM calendar_tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, *, status: TaskStatus | None = None,
                   overdue_since: datetime | None = None,
                   project: str = "", subject: str = "",
                   limit: int | None = None) -> list[CalendarTask]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if overdue_since is not None:
            clauses.append("due_at IS NOT NULL AND due_at <= ? AND status NOT IN ('completed','cancelled')")
            params.append(overdue_since.isoformat())
        if project:
            clauses.append("project = ?")
            params.append(project)
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        limit = limit or self._config.max_task_results
        sql = "SELECT * FROM calendar_tasks"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(due_at, '9999-12-31T00:00:00+00:00') LIMIT ?"
        params.append(limit)
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def _task_from_row(self, row) -> CalendarTask:
        return CalendarTask(
            task_id=row["task_id"], title=row["title"],
            description=row["description"], due_at=_dt(row["due_at"]),
            priority=row["priority"], status=row["status"],
            created_at=_dt(row["created_at"]), completed_at=_dt(row["completed_at"]),
            subject=row["subject"], project=row["project"],
            tags=tuple(json.loads(row["tags"])))

    def delete_task(self, task_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM calendar_tasks WHERE task_id=?", (task_id,))
            conn.execute(
                "DELETE FROM calendar_reminders WHERE target_id=? AND target_kind='task'",
                (task_id,))

    # ---- subjects ----

    def upsert_subject(self, subject: Subject) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO subjects(subject_id, name, category) VALUES(?,?,?)
                   ON CONFLICT(subject_id) DO UPDATE SET
                     name=excluded.name, category=excluded.category""",
                (str(subject.subject_id), subject.name, subject.category))

    def list_subjects(self, limit: int = 128) -> list[Subject]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM subjects ORDER BY name LIMIT ?", (min(limit, 128),)).fetchall()
        return [Subject(subject_id=row["subject_id"], name=row["name"],
                        category=row["category"]) for row in rows]

    # ---- timetable ----

    def insert_timetable(self, entry: TimetableEntry) -> None:
        self._upsert_timetable(entry)

    def update_timetable(self, entry: TimetableEntry) -> None:
        self._upsert_timetable(entry)

    def _upsert_timetable(self, entry: TimetableEntry) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO timetable_entries
                   (entry_id, subject, teacher, room, weekday, start_time,
                    end_time, term, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(entry_id) DO UPDATE SET
                     subject=excluded.subject, teacher=excluded.teacher,
                     room=excluded.room, weekday=excluded.weekday,
                     start_time=excluded.start_time, end_time=excluded.end_time,
                     term=excluded.term, notes=excluded.notes""",
                (str(entry.entry_id), entry.subject, entry.teacher, entry.room,
                 entry.weekday.value, entry.start_time.isoformat(),
                 entry.end_time.isoformat(), entry.term, entry.notes))

    def list_timetable(self, *, weekday: Weekday | None = None,
                       term: str = "", limit: int = 256) -> list[TimetableEntry]:
        clauses: list[str] = []
        params: list[Any] = []
        if weekday is not None:
            clauses.append("weekday = ?")
            params.append(weekday.value)
        if term:
            clauses.append("term = ?")
            params.append(term)
        sql = "SELECT * FROM timetable_entries"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY start_time LIMIT ?"
        params.append(min(limit, 256))
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._timetable_from_row(row) for row in rows]

    def delete_timetable_entry(self, entry_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM timetable_entries WHERE entry_id=?", (entry_id,))

    def get_timetable_entry(self, entry_id: str) -> TimetableEntry | None:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM timetable_entries WHERE entry_id=?", (entry_id,)).fetchone()
        return self._timetable_from_row(row) if row else None

    def _timetable_from_row(self, row) -> TimetableEntry:
        return TimetableEntry(
            entry_id=row["entry_id"], subject=row["subject"], teacher=row["teacher"],
            room=row["room"], weekday=row["weekday"],
            start_time=datetime.fromisoformat("2000-01-01T" + row["start_time"]).time(),
            end_time=datetime.fromisoformat("2000-01-01T" + row["end_time"]).time(),
            term=row["term"], notes=row["notes"])

    def occurrences_for_date(self, day: date, *, tz, term: str = "") -> list[ScheduleOccurrence]:
        weekday = weekday_index(Weekday(list(Weekday)[day.weekday()]))
        entries = [entry for entry in self.list_timetable(term=term)
                   if weekday_index(entry.weekday) == weekday]
        from datetime import time as _time, datetime as _dt2
        occurrences: list[ScheduleOccurrence] = []
        for entry in entries:
            start = _dt2.combine(day, entry.start_time, tzinfo=tz)
            end = _dt2.combine(day, entry.end_time, tzinfo=tz)
            if end <= start:
                continue
            occurrences.append(ScheduleOccurrence(
                entry_id=entry.entry_id, subject=entry.subject, teacher=entry.teacher,
                room=entry.room, date=day, start=start, end=end,
                term=entry.term, notes=entry.notes))
        return occurrences

    # ---- workflows ----

    def upsert_workflow(self, definition: WorkflowDefinition) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO workflow_definitions(workflow_id, name, steps, enabled, created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(workflow_id) DO UPDATE SET
                     name=excluded.name, steps=excluded.steps, enabled=excluded.enabled""",
                (str(definition.workflow_id), definition.name,
                 json.dumps([step.model_dump(mode="json") for step in definition.steps]),
                 int(definition.enabled), definition.created_at.isoformat()))

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_definitions WHERE workflow_id=?",
                (workflow_id,)).fetchone()
        if not row:
            return None
        steps = tuple(WorkflowStep(**item) for item in json.loads(row["steps"])) if row["steps"] else ()
        return WorkflowDefinition(
            workflow_id=row["workflow_id"], name=row["name"], steps=steps,
            enabled=bool(row["enabled"]), created_at=_dt(row["created_at"]))

    def list_workflows(self, *, enabled_only: bool = False, limit: int = 128) -> list[WorkflowDefinition]:
        sql = "SELECT * FROM workflow_definitions"
        params: list[Any] = []
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at LIMIT ?"
        params.append(min(limit, 128))
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self.get_workflow(row["workflow_id"]) for row in rows if row["workflow_id"]]

    def delete_workflow(self, workflow_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM workflow_triggers WHERE workflow_id=?", (workflow_id,))
            conn.execute("DELETE FROM workflow_definitions WHERE workflow_id=?", (workflow_id,))

    def upsert_trigger(self, trigger: WorkflowTrigger) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO workflow_triggers
                   (trigger_id, workflow_id, trigger_type, at_time, before_event,
                    after_event, enabled, last_fired_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(trigger_id) DO UPDATE SET
                     workflow_id=excluded.workflow_id, trigger_type=excluded.trigger_type,
                     at_time=excluded.at_time, before_event=excluded.before_event,
                     after_event=excluded.after_event, enabled=excluded.enabled,
                     last_fired_at=excluded.last_fired_at""",
                (str(trigger.trigger_id), str(trigger.workflow_id),
                 trigger.trigger_type.value,
                 trigger.at_time.isoformat() if trigger.at_time else None,
                 str(trigger.before_event) if trigger.before_event else None,
                 str(trigger.after_event) if trigger.after_event else None,
                 int(trigger.enabled),
                 trigger.last_fired_at.isoformat() if trigger.last_fired_at else None))

    def list_triggers(self, *, enabled_only: bool = False, limit: int = 128) -> list[WorkflowTrigger]:
        sql = "SELECT * FROM workflow_triggers"
        params: list[Any] = []
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY trigger_id LIMIT ?"
        params.append(min(limit, 128))
        with self._db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [WorkflowTrigger(
            trigger_id=row["trigger_id"], workflow_id=row["workflow_id"],
            trigger_type=row["trigger_type"],
            at_time=datetime.fromisoformat("2000-01-01T" + row["at_time"]).time() if row["at_time"] else None,
            before_event=row["before_event"], after_event=row["after_event"],
            enabled=bool(row["enabled"]), last_fired_at=_dt(row["last_fired_at"]))
            for row in rows]

    def delete_trigger(self, trigger_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM workflow_triggers WHERE trigger_id=?", (trigger_id,))

    def mark_trigger_fired(self, trigger_id: str, fired_at: datetime) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE workflow_triggers SET last_fired_at=? WHERE trigger_id=? AND enabled=1",
                (fired_at.isoformat(), trigger_id))