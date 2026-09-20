from datetime import datetime, timedelta, timezone

from app.calendar.migration import CALENDAR_MIGRATIONS
from app.database.config import DatabaseConfig
from app.database.service import DatabaseService
from app.memory.migration import MEMORY_MIGRATIONS
from app.proactive.engine import ProactiveScheduler
from app.proactive.migration import PROACTIVE_MIGRATIONS
from app.proactive.models import ProactiveWorkflow, WorkflowState


def build_scheduler(tmp_path, notifier=None):
    database = DatabaseService(
        DatabaseConfig(db_path=str(tmp_path / "jarvis.db")),
        extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS + PROACTIVE_MIGRATIONS,
    )
    database.initialize()
    return database, ProactiveScheduler(database, poll_seconds=60, notifier=notifier)


def test_due_notification_persists_history_and_is_idempotent(tmp_path):
    messages = []
    database, scheduler = build_scheduler(tmp_path, messages.append)
    workflow = scheduler.schedule(ProactiveWorkflow(
        name="reminder", trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        notification="local reminder",
    ))

    assert scheduler.run_cycle() == 1
    assert scheduler.run_cycle() == 0
    assert messages == ["local reminder"]
    assert scheduler.history(workflow.workflow_id)[0].state is WorkflowState.COMPLETED

    restarted = ProactiveScheduler(database, poll_seconds=60, notifier=messages.append)
    assert restarted.run_cycle() == 0


def test_failure_retries_once_then_fails(tmp_path):
    def failing(_message):
        raise RuntimeError("notification unavailable")

    _, scheduler = build_scheduler(tmp_path, failing)
    workflow = scheduler.schedule(ProactiveWorkflow(
        name="retry", trigger_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        notification="retry me", max_retries=1,
    ))

    assert scheduler.run_cycle() == 0
    assert scheduler.run_cycle() == 0
    history = scheduler.history(workflow.workflow_id)
    assert len(history) == 2
    assert history[-1].state is WorkflowState.FAILED


def test_kill_switch_cancels_pending_but_reenable_restores_only_disabled(tmp_path):
    _, scheduler = build_scheduler(tmp_path)
    disabled_workflow = scheduler.schedule(ProactiveWorkflow(
        name="disabled", trigger_at=datetime.now(timezone.utc) + timedelta(hours=1), notification="x",
    ))
    user_cancelled = scheduler.schedule(ProactiveWorkflow(
        name="cancelled", trigger_at=datetime.now(timezone.utc) + timedelta(hours=1), notification="y",
    ))
    assert scheduler.cancel(user_cancelled.workflow_id)

    scheduler.disable()
    scheduler.enable()

    assert scheduler.run_cycle() == 0
    assert scheduler.history(disabled_workflow.workflow_id) == []
    assert scheduler.enabled
