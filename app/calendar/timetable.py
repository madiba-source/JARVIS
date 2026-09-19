"""Timetable planner: weekly entries over a date range, next classes, totals."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendar.clock import CalendarClock
from app.calendar.config import CalendarConfig
from app.calendar.models import ScheduleOccurrence, TimeRange
from app.calendar.service import CalendarService
from app.calendar.store import CalendarStore


class TimetablePlanner:
    """High-level timetable questions; stores and queries live on the service."""

    def __init__(self, service: CalendarService, config: CalendarConfig,
                 clock: CalendarClock | None = None) -> None:
        self._service = service
        self._config = config
        self._clock = clock or service.clock

    @property
    def timezone(self) -> ZoneInfo:
        return self._service.timezone

    def occurrences(self, start: date, end: date,
                    *, term: str = "") -> list[ScheduleOccurrence]:
        if end < start:
            return []
        if (end - start).days > 366:
            end = start + timedelta(days=366)
        store: CalendarStore = self._service.store()
        results: list[ScheduleOccurrence] = []
        day = start
        while day <= end:
            results.extend(store.occurrences_for_date(day, tz=self.timezone, term=term))
            day += timedelta(days=1)
        results.sort(key=lambda item: (item.date, item.start))
        return results[: max(1, self._config.max_events_returned * 4)]

    def for_subject(self, subject: str, *, term: str = "") -> list[TimetableEntryLite]:
        entries = self._service.timetable(term=term)
        return [TimetableEntryLite(
            entry_id=entry.entry_id, subject=entry.subject, teacher=entry.teacher,
            room=entry.room, weekday=entry.weekday, start_time=entry.start_time,
            end_time=entry.end_time, term=entry.term)
            for entry in entries if entry.subject == subject][:128]

    def hours_in_window(self, start: date, end: date, *, term: str = "") -> float:
        total = 0.0
        for occurrence in self.occurrences(start, end, term=term):
            total += (occurrence.end - occurrence.start).total_seconds() / 3600
        return round(total, 2)

    def busy_ranges(self, day: date, *, term: str = "") -> list[TimeRange]:
        zone = self.timezone
        from datetime import time as _time
        morning = datetime.combine(day, _time.min, tzinfo=zone)
        day_end = morning + timedelta(days=1)
        ranges: list[TimeRange] = []
        for occurrence in self.occurrences(day, day, term=term):
            if occurrence.end > morning and occurrence.start < day_end:
                ranges.append(TimeRange(start=max(occurrence.start, morning),
                                        end=min(occurrence.end, day_end)))
        return ranges


class TimetableEntryLite:
    __slots__ = ("entry_id", "subject", "teacher", "room", "weekday",
                 "start_time", "end_time", "term")

    def __init__(self, *, entry_id, subject, teacher, room, weekday,
                 start_time, end_time, term) -> None:
        self.entry_id = entry_id
        self.subject = subject
        self.teacher = teacher
        self.room = room
        self.weekday = weekday
        self.start_time = start_time
        self.end_time = end_time
        self.term = term