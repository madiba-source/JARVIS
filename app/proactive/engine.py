"""Persistent, bounded proactive notification scheduler."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from app.core.events import EventBus
from app.database.service import DatabaseService

from .models import ProactiveEvent, ProactiveWorkflow, WorkflowRun, WorkflowState

MAX_QUEUE = 128


class ProactiveScheduler:
    """One idle-waiting thread for deterministic, notification-only workflows."""

    def __init__(self, database: DatabaseService, *, poll_seconds: float = 60.0,
                 max_queue: int = MAX_QUEUE, notifier: Callable[[str], None] | None = None,
                 event_bus: EventBus | None = None) -> None:
        self.database = database
        self.poll_seconds = max(1.0, min(float(poll_seconds), 3600.0))
        self.max_queue = max(1, min(max_queue, MAX_QUEUE))
        self.notifier = notifier
        self.event_bus = event_bus
        self._stop = threading.Event()
        self._kill_switch = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._active = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def enabled(self) -> bool:
        return not self._kill_switch.is_set()

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="proactive-scheduler", daemon=True)
        self._thread.start()
        self._publish("PROACTIVE_SCHEDULER_STARTED")

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, timeout))
        self._thread = None
        self._publish("PROACTIVE_SCHEDULER_STOPPED")

    def disable(self) -> None:
        """Emergency kill switch: stop scheduling and cancel pending workflows."""
        self._kill_switch.set()
        self.stop()
        with self.database.transaction() as conn:
            conn.execute("UPDATE proactive_workflows SET enabled=0, state='cancelled', last_error='disabled' WHERE state IN ('pending','running')")
        self._publish("PROACTIVE_AUTOMATION_DISABLED")

    def enable(self) -> None:
        self._kill_switch.clear()
        with self.database.transaction() as conn:
            conn.execute("UPDATE proactive_workflows SET enabled=1, state='pending', last_error=NULL WHERE state='cancelled' AND last_error='disabled'")
        self.start()
        self._publish("PROACTIVE_AUTOMATION_ENABLED")

    def schedule(self, workflow: ProactiveWorkflow) -> ProactiveWorkflow:
        if not self.enabled:
            raise RuntimeError("proactive automation is disabled")
        with self.database.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) FROM proactive_workflows WHERE enabled=1 AND state='pending'").fetchone()[0]
            if count >= self.max_queue:
                raise RuntimeError("proactive workflow queue is full")
            conn.execute(
                """INSERT INTO proactive_workflows
                   (workflow_id,name,trigger_at,notification,enabled,state,retry_count,max_retries,max_runtime_seconds,created_at,last_error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (str(workflow.workflow_id), workflow.name, workflow.trigger_at.isoformat(), workflow.notification,
                 int(workflow.enabled), workflow.state.value, workflow.retry_count, workflow.max_retries,
                 workflow.max_runtime_seconds, workflow.created_at.isoformat(), workflow.last_error))
        self._publish("PROACTIVE_WORKFLOW_SCHEDULED", workflow_id=str(workflow.workflow_id))
        return workflow

    def cancel(self, workflow_id: UUID | str) -> bool:
        with self.database.transaction() as conn:
            cursor = conn.execute("UPDATE proactive_workflows SET enabled=0,state='cancelled',last_error='cancelled_by_user' WHERE workflow_id=? AND state IN ('pending','running')", (str(workflow_id),))
        if cursor.rowcount:
            self._publish("PROACTIVE_WORKFLOW_CANCELLED", workflow_id=str(workflow_id))
            return True
        return False

    def normalize(self, event: dict[str, object]) -> ProactiveEvent:
        """Normalize an internal event without granting it execution authority."""
        return ProactiveEvent.model_validate(event)

    def run_cycle(self, now: datetime | None = None) -> int:
        if not self.enabled:
            return 0
        cutoff = now or datetime.now(timezone.utc)
        with self.database.connection_manager.connection() as rows:
            due = rows.execute(
                "SELECT * FROM proactive_workflows WHERE enabled=1 AND state='pending' AND trigger_at<=? ORDER BY trigger_at LIMIT ?",
                (cutoff.isoformat(), min(self.max_queue, 32)),
            ).fetchall()
        completed = 0
        for row in due:
            if self._stop.is_set() or not self.enabled:
                break
            if self._claim(row["workflow_id"]) and self._run_row(row):
                completed += 1
        return completed

    def history(self, workflow_id: UUID | str) -> list[WorkflowRun]:
        with self.database.transaction() as conn:
            rows = conn.execute("SELECT * FROM proactive_workflow_runs WHERE workflow_id=? ORDER BY started_at", (str(workflow_id),)).fetchall()
        return [WorkflowRun(run_id=row["run_id"], workflow_id=row["workflow_id"], state=row["state"], started_at=_dt(row["started_at"]), finished_at=_dt(row["finished_at"]), duration_ms=row["duration_ms"], retry_count=row["retry_count"], error=row["error"]) for row in rows]

    def _loop(self) -> None:
        while not self._stop.is_set() and self.enabled:
            try:
                self.run_cycle()
            except Exception:
                self._publish("PROACTIVE_SCHEDULER_ERROR")
            self._stop.wait(self.poll_seconds)

    def _claim(self, workflow_id: str) -> bool:
        with self.database.transaction() as conn:
            cursor = conn.execute("UPDATE proactive_workflows SET state='running' WHERE workflow_id=? AND enabled=1 AND state='pending'", (workflow_id,))
        return cursor.rowcount == 1

    def _run_row(self, row) -> bool:
        started = datetime.now(timezone.utc)
        run_id = str(uuid4())
        error = None
        state = WorkflowState.COMPLETED
        try:
            if self.notifier is not None:
                self.notifier(str(row["notification"])[:512])
        except Exception as exc:
            state = WorkflowState.FAILED
            error = type(exc).__name__
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        retry_count = int(row["retry_count"])
        with self.database.transaction() as conn:
            conn.execute("INSERT INTO proactive_workflow_runs(run_id,workflow_id,state,started_at,finished_at,duration_ms,retry_count,error) VALUES(?,?,?,?,?,?,?,?)", (run_id, row["workflow_id"], state.value, started.isoformat(), datetime.now(timezone.utc).isoformat(), duration, retry_count, error))
            if state is WorkflowState.COMPLETED:
                conn.execute("UPDATE proactive_workflows SET state='completed',last_error=NULL WHERE workflow_id=?", (row["workflow_id"],))
            elif retry_count < int(row["max_retries"]) and self.enabled:
                conn.execute("UPDATE proactive_workflows SET state='pending',retry_count=retry_count+1,last_error=? WHERE workflow_id=?", (error, row["workflow_id"]))
            else:
                conn.execute("UPDATE proactive_workflows SET state='failed',last_error=? WHERE workflow_id=?", (error, row["workflow_id"]))
        self._publish("PROACTIVE_WORKFLOW_COMPLETED" if state is WorkflowState.COMPLETED else "PROACTIVE_WORKFLOW_FAILED", workflow_id=row["workflow_id"], error=error)
        return state is WorkflowState.COMPLETED

    def _publish(self, event_type: str, **metadata: str | None) -> None:
        if self.event_bus is not None:
            self.event_bus.publish({"event_type": event_type, **metadata})


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
