"""Deterministic temporal expression parser (today, next monday, at 10am...)."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo

from app.calendar.clock import CalendarClock, make_tz
from app.calendar.models import Weekday, weekday_index

_HOUR_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.IGNORECASE)


class ResolvedTime:
    __slots__ = ("date", "time", "start", "end", "ambiguous", "label")

    def __init__(self, *, date_: date | None = None, time_: time | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 ambiguous: bool = False, label: str = "") -> None:
        self.date = date_
        self.time = time_
        self.start = start
        self.end = end
        self.ambiguous = ambiguous
        self.label = label


class TemporalResolver:
    def __init__(self, clock: CalendarClock, timezone_name: str = "UTC") -> None:
        self._clock = clock
        self._tz = make_tz(timezone_name)

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return self._clock.now()

    def _today(self) -> date:
        return self._clock.today(self._tz)

    def _aware(self, day: date, moment: time) -> datetime:
        from app.calendar.clock import local_wall_time
        return local_wall_time(day, moment, self._tz)

    def resolve(self, expression: str) -> ResolvedTime | None:
        text = " ".join(expression.strip().split())
        if not text:
            return ResolvedTime(label="empty")
        lowered = text.lower()

        if lowered in ("today", "tonight", "today at now"):
            return self._today_time(text)
        if lowered == "tomorrow":
            return self._around(self._today() + timedelta(days=1), label="tomorrow")
        if lowered == "yesterday":
            return self._around(self._today() - timedelta(days=1), label="yesterday")

        weekday = self._parse_weekday(lowered)
        if weekday:
            return self._weekday_expression(weekday, lowered)

        if lowered == "this week":
            return self._this_week()
        if lowered == "next week":
            return self._next_week()
        if lowered.startswith("in "):
            return self._relative(lowered[3:].strip())
        if lowered.startswith("at "):
            return self._at_time(lowered[3:].strip(), self._today())

        match = self._parse_date(lowered)
        if match:
            day, rest = match
            return self._around(day, rest=rest, label=text)

        if lowered == "next week":
            return self._next_week()

        return None

    def _today_time(self, text: str) -> ResolvedTime:
        if "at " in text:
            piece = text.split("at ", 1)[1].strip()
            moment = self._parse_clock(piece)
            if moment is None:
                return self._around(self._today(), label="today")
            aware = self._aware(self._today(), moment)
            return ResolvedTime(date_=self._today(), time_=moment, start=aware,
                                end=aware + timedelta(hours=1), label="today")
        return self._around(self._today(), label="today")

    def _around(self, day: date, rest: str = "", label: str = "") -> ResolvedTime:
        moment = self._parse_clock(rest.strip()) if rest else None
        if moment is None and rest:
            return ResolvedTime(date_=day, ambiguous=True, label=label)
        start = None
        end = None
        if moment is not None:
            aware = self._aware(day, moment)
            start = aware
            end = aware + timedelta(hours=1)
        return ResolvedTime(date_=day, time_=moment, start=start, end=end,
                            ambiguous=False, label=label)

    def _parse_weekday(self, lowered: str) -> tuple[Weekday, str] | None:
        for day in Weekday:
            name = day.value
            if lowered == name:
                return day, "this"
            if lowered.startswith("next " + name):
                return day, "next"
            if lowered.startswith("this " + name):
                return day, "this"
            if lowered.startswith("last " + name):
                return day, "previous"
        return None

    def _weekday_expression(self, day: Weekday, scope: str) -> ResolvedTime:
        today = self._today()
        current = today.weekday()
        target = weekday_index(day)
        if scope == "this":
            delta = (target - current) % 7
            if delta == 0:
                delta = 0
            day = today + timedelta(days=delta)
            return self._around(day, label=getattr(Weekday, day.strftime("%A").upper()).value)
        if scope == "next":
            delta = (target - current) % 7
            delta = delta if delta != 0 else 7
            day = today + timedelta(days=delta)
            return self._around(day, label="next " + day.value)
        if scope == "previous":
            delta = (current - target) % 7
            delta = delta if delta != 0 else 7
            day = today - timedelta(days=delta)
            return self._around(day, label="last " + day.value)
        return ResolvedTime(date_=today, ambiguous=True, label=day.value)

    def _this_week(self) -> ResolvedTime:
        today = self._today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return ResolvedTime(date_=monday, start=self._aware(monday, time.min),
                            end=self._aware(sunday, time.max) + timedelta(seconds=1),
                            label="this week")

    def _next_week(self) -> ResolvedTime:
        today = self._today()
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        sunday = monday + timedelta(days=6)
        return ResolvedTime(date_=monday, start=self._aware(monday, time.min),
                            end=self._aware(sunday, time.max) + timedelta(seconds=1),
                            label="next week")

    def _relative(self, piece: str) -> ResolvedTime | None:
        match = re.match(r"^(\d+)\s+(minutes?|hours?|days?|weeks?)\s*(from\s+now)?$", piece)
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2)
        now = self.now()
        if unit.startswith("minute"):
            result = now + timedelta(minutes=amount)
        elif unit.startswith("hour"):
            result = now + timedelta(hours=amount)
        elif unit.startswith("day"):
            result = now + timedelta(days=amount)
        else:
            result = now + timedelta(weeks=amount)
        if amount > 3650:
            return ResolvedTime(ambiguous=True, label="relative too far")
        return ResolvedTime(date_=result.date(), start=result, end=result + timedelta(hours=1),
                            label=f"in {amount} {unit}")

    def _at_time(self, piece: str, day: date) -> ResolvedTime | None:
        moment = self._parse_clock(piece)
        if moment is None:
            return None
        aware = self._aware(day, moment)
        return ResolvedTime(date_=day, time_=moment, start=aware,
                            end=aware + timedelta(hours=1), label=f"at {piece}")

    def _parse_clock(self, piece: str) -> time | None:
        match = _HOUR_RE.match(piece.strip())
        if not match:
            return None
        hour_raw = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridian = (match.group(3) or "").lower()
        if meridian:
            if hour_raw == 12:
                hour = 0 if meridian == "am" else 12
            else:
                hour = hour_raw + (12 if meridian == "pm" else 0)
        else:
            hour = hour_raw
        if hour > 23 or minute > 59:
            return None
        return time(hour=hour, minute=minute)

    def _parse_date(self, lowered: str) -> tuple[date, str] | None:
        match = re.match(r"^(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s*(\d{4})?$", lowered)
        if match:
            month = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
                     "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
                     "november": 11, "december": 12}[match.group(2)]
            year = int(match.group(3)) if match.group(3) else self._today().year
            return date(year, month, int(match.group(1))), ""
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(.+))?$", lowered)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))), (match.group(4) or "")
        return None