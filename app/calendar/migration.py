"""Calendar SQLite schema. Version 3 keeps the registry contiguous (1, 2, 3)."""

from __future__ import annotations

import sqlite3


def calendar_schema(conn: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE calendar_events (
            event_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'event',
            all_day INTEGER NOT NULL DEFAULT 0,
            start TEXT, end TEXT, start_date TEXT, end_date TEXT,
            tz TEXT NOT NULL DEFAULT 'UTC', recurrence_id TEXT,
            status TEXT NOT NULL DEFAULT 'active', source TEXT NOT NULL DEFAULT 'calendar',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            CHECK (all_day IN (0,1)),
            CHECK ((all_day = 0 AND start IS NOT NULL AND end IS NOT NULL
                    AND start_date IS NULL AND end_date IS NULL)
                OR (all_day = 1 AND start IS NULL AND end IS NULL
                    AND start_date IS NOT NULL AND end_date IS NOT NULL)))""",
        "CREATE INDEX calendar_events_start ON calendar_events(start,status)",
        "CREATE INDEX calendar_events_all_day ON calendar_events(start_date,end_date,status)",
        """CREATE TABLE calendar_event_versions (
            event_id TEXT NOT NULL REFERENCES calendar_events(event_id),
            version INTEGER NOT NULL, record TEXT NOT NULL,
            PRIMARY KEY(event_id,version))""",
        """CREATE TABLE calendar_recurrences (
            recurrence_id TEXT PRIMARY KEY, freq TEXT NOT NULL,
            interval INTEGER NOT NULL, by_day TEXT NOT NULL DEFAULT '[]',
            by_month_day INTEGER, count INTEGER, until TEXT,
            dtstart TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE calendar_reminders (
            reminder_id TEXT PRIMARY KEY, target_id TEXT NOT NULL,
            target_kind TEXT NOT NULL, remind_at TEXT NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'announce',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, fired_at TEXT)""",
        "CREATE INDEX calendar_reminders_due ON calendar_reminders(status,remind_at)",
        """CREATE TABLE calendar_tasks (
            task_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', due_at TEXT,
            priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, completed_at TEXT,
            subject TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]')""",
        "CREATE INDEX calendar_tasks_due ON calendar_tasks(status,due_at)",
        """CREATE TABLE subjects (
            subject_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '')""",
        """CREATE TABLE timetable_entries (
            entry_id TEXT PRIMARY KEY, subject TEXT NOT NULL,
            teacher TEXT NOT NULL DEFAULT '', room TEXT NOT NULL DEFAULT '',
            weekday TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
            term TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX timetable_weekday ON timetable_entries(weekday,term)",
        """CREATE TABLE workflow_definitions (
            workflow_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            steps TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL)""",
        """CREATE TABLE workflow_triggers (
            trigger_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL
                REFERENCES workflow_definitions(workflow_id),
            trigger_type TEXT NOT NULL, at_time TEXT, before_event TEXT, after_event TEXT,
            enabled INTEGER NOT NULL DEFAULT 1, last_fired_at TEXT)""",
        "CREATE INDEX workflow_trigger_due ON workflow_triggers(trigger_type,enabled)",
    )
    for statement in statements:
        conn.execute(statement)


CALENDAR_MIGRATIONS = [(3, "calendar, timetable, reminders and workflows", calendar_schema)]