from datetime import datetime, timedelta, timezone

import pytest

from app.calendar.config import CalendarConfig
from app.calendar.models import QueryKind, CalendarQuery
from app.calendar.runtime import CalendarRuntime
from app.core.events import EventBus


def test_calendar_runtime_persists_queries_conflicts_and_reminders(tmp_path) -> None:
    config = CalendarConfig(enabled=True, scheduler_enabled=False)
    runtime = CalendarRuntime(tmp_path, config, EventBus())
    assert runtime.available
    service = runtime.service
    assert service is not None

    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    event = service.create_event(title="Planning", start=start, end=start + timedelta(hours=1))
    assert service.get_event(str(event.event_id)) is not None
    reminder = service.create_reminder(target_id=event.event_id, target_kind="event",
                                       remind_at=start - timedelta(minutes=1))
    fired = service.fire_due_reminders(now=start)
    assert str(reminder.reminder_id) == str(fired[0].reminder_id)

    with pytest.raises(Exception):
        service.create_event(title="Conflict", start=start + timedelta(minutes=30),
                             end=start + timedelta(hours=2))

    result = service.query(CalendarQuery(kind=QueryKind.DAY, date=start.date()))
    assert any(item["title"] == "Planning" for item in result["events"])
    runtime.close()
    assert not runtime.available