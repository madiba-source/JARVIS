"""SQLite schema for bounded proactive workflows and execution history."""

import sqlite3


def proactive_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE proactive_workflows (
            workflow_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            trigger_at TEXT NOT NULL, notification TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'pending',
            retry_count INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 0,
            max_runtime_seconds REAL NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL, last_error TEXT)"""
    )
    conn.execute("CREATE INDEX proactive_workflows_due ON proactive_workflows(enabled,state,trigger_at)")
    conn.execute(
        """CREATE TABLE proactive_workflow_runs (
            run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
            state TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
            duration_ms REAL, retry_count INTEGER NOT NULL DEFAULT 0, error TEXT)"""
    )
    conn.execute("CREATE INDEX proactive_runs_workflow ON proactive_workflow_runs(workflow_id,started_at)")


PROACTIVE_MIGRATIONS = [(4, "bounded proactive workflows and history", proactive_schema)]
