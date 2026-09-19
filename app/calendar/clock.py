"""Inject clocks so all calendar logic is deterministic and DST-safe."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo


def make_tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


class CalendarClock(Protocol):
    def now(self) -> datetime:
        """Current instant as an aware UTC datetime."""

    def today(self, tz: ZoneInfo | None = None) -> date:
        """Local calendar date, defaulting to UTC when tz is None."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def today(self, tz: ZoneInfo | None = None) -> date:
        return (self.now() if tz is None else datetime.now(tz)).date()


class FixedClock:
    """Deterministic test clock; returns a fixed instant."""

    def __init__(self, fixed: datetime) -> None:
        if fixed.tzinfo is None:
            fixed = fixed.replace(tzinfo=timezone.utc)
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed

    def today(self, tz: ZoneInfo | None = None) -> date:
        return (self._fixed if tz is None else self._fixed.astimezone(tz)).date()


def local_wall_time(day: date, moment: time, tz: ZoneInfo) -> datetime:
    """Build an aware local datetime for a wall-clock day/time.

    On DST gaps (nonexistent local times) the wall time is pushed forward so
    construction never raises; ambiguous times resolve to their first
    occurrence (fold=0). Results are documented and deterministic.
    """
    naive = datetime.combine(day, moment)
    aware = naive.replace(tzinfo=tz).astimezone(tz)
    return aware


def local_floor(dt: datetime, tz: ZoneInfo) -> datetime:
    """Convert an instant to its local wall time interpreted in tz."""
    return dt.astimezone(tz)


def shift_days(day: date, delta: int) -> date:
    return day + timedelta(days=delta)