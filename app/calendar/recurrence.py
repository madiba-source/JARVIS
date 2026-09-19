"""Bounded deterministic recurrence expansion. Never generates unbounded sets."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.calendar.models import CalendarRecurrence, Weekday, weekday_index

_MAX_LOOP_ITERATIONS = 100_000


def _month_day(date_: date) -> int:
    return date_.day


def _advance_month(dt: datetime, interval: int) -> datetime:
    month_index = dt.year * 12 + (dt.month - 1) + interval
    year, month = divmod(month_index, 12)
    year, month = year, month + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _next_candidate(cursor: datetime, rule: CalendarRecurrence) -> datetime:
    freq = rule.freq.value
    if freq == "daily":
        return cursor + timedelta(days=rule.interval)
    if freq == "weekly":
        return cursor + timedelta(weeks=rule.interval)
    if freq == "monthly":
        return _advance_month(cursor, rule.interval)
    raise ValueError("unknown recurrence frequency")


def _weekly_dates(anchor: date, rule: CalendarRecurrence, include_anchor: bool = False) -> list[date]:
    """Candidate dates within the week containing the anchor that match by_day."""
    if not rule.by_day:
        return [anchor]
    base = anchor - timedelta(days=anchor.weekday())
    wanted = {weekday_index(day) for day in rule.by_day}
    if include_anchor and anchor.weekday() not in wanted:
        return []
    dates = [base + timedelta(days=day) for day in sorted(wanted)]
    if include_anchor:
        dates = [day for day in dates if day >= anchor]
    return dates


def expand(
    rule: CalendarRecurrence,
    *,
    max_occurrences: int,
    horizon_days: int,
) -> list[datetime]:
    """Return occurrence instants, strictly bounded by count, until, max and horizon."""
    if max_occurrences <= 0:
        return []
    horizon = rule.dtstart + timedelta(days=horizon_days)
    fixed_until = rule.until

    results: list[datetime] = []
    remaining = max_occurrences
    if rule.count is not None:
        remaining = min(remaining, rule.count)

    iterations = 0
    freq = rule.freq.value
    cursor_date = rule.dtstart.date()
    cursor_time = rule.dtstart.timetz() if freq != "daily" else rule.dtstart.timetz()
    tz = rule.dtstart.tzinfo

    if freq in ("daily", "monthly"):
        cursor = rule.dtstart
        while len(results) < remaining:
            iterations += 1
            if iterations > _MAX_LOOP_ITERATIONS:
                break
            if cursor > horizon:
                break
            if fixed_until is not None and cursor > fixed_until:
                break
            if freq == "monthly" and rule.by_month_day is not None:
                candidate = cursor.replace(day=min(rule.by_month_day, _days_in_month(cursor.year, cursor.month)))
                candidate = candidate.replace(
                    hour=cursor.hour, minute=cursor.minute, second=cursor.second,
                    microsecond=cursor.microsecond, tzinfo=tz)
                if rule.by_month_day <= _days_in_month(cursor.year, cursor.month):
                    results.append(candidate)
            else:
                results.append(cursor)
            cursor = _next_candidate(cursor, rule)
    elif freq == "weekly":
        weeks_interval = rule.interval
        week = cursor_date
        while len(results) < remaining:
            iterations += 1
            if iterations > _MAX_LOOP_ITERATIONS:
                break
            candidates = _weekly_dates(week, rule, include_anchor=True)
            for day in candidates:
                if len(results) >= remaining:
                    break
                candidate = datetime.combine(day, cursor_time, tzinfo=tz)
                if candidate > horizon:
                    break
                if fixed_until is not None and candidate > fixed_until:
                    break
                if candidate >= rule.dtstart:
                    results.append(candidate)
            if any(day > horizon.date() or (fixed_until is not None and datetime.combine(day, cursor_time, tzinfo=tz) > fixed_until) for day in candidates):
                break
            week = week + timedelta(weeks=weeks_interval)
    return results[:max_occurrences]