"""Interval arithmetic for schedules: overlap, merge, conflict and free time."""

from __future__ import annotations

from app.calendar.models import ScheduleConflict, TimeRange


def overlaps(a: TimeRange, b: TimeRange) -> bool:
    return a.start < b.end and b.start < a.end


def merge_intervals(intervals: list[TimeRange]) -> list[TimeRange]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item.start)
    merged: list[TimeRange] = []
    current = ordered[0]
    for interval in ordered[1:]:
        if interval.start <= current.end:
            if interval.end > current.end:
                current = TimeRange(start=current.start, end=interval.end)
        else:
            merged.append(current)
            current = interval
    merged.append(current)
    return merged


def detect_conflicts(intervals: list[TimeRange], parties: list[str],
                     kind) -> list[ScheduleConflict]:
    """Pairwise overlap detection for equally-typed intervals."""
    conflicts: list[ScheduleConflict] = []
    count = len(intervals)
    for left in range(count):
        for right in range(left + 1, count):
            if overlaps(intervals[left], intervals[right]):
                start = max(intervals[left].start, intervals[right].start)
                end = min(intervals[left].end, intervals[right].end)
                conflicts.append(ScheduleConflict(
                    kind=kind, start=start, end=end,
                    parties=(parties[left], parties[right])))
    return conflicts


def free_time(busy: list[TimeRange], window: TimeRange,
              minimum_duration_minutes: int = 0) -> list[TimeRange]:
    """Complement of busy intervals inside a window, filtered by duration."""
    merged = merge_intervals(busy)
    slots: list[TimeRange] = []
    cursor = window.start
    for interval in merged:
        if interval.end <= cursor:
            continue
        if interval.start > cursor:
            slots.append(TimeRange(start=cursor, end=min(interval.start, window.end)))
        cursor = max(cursor, interval.end)
        if cursor >= window.end:
            break
    if cursor < window.end:
        slots.append(TimeRange(start=cursor, end=window.end))
    if minimum_duration_minutes > 0:
        required = minimum_duration_minutes * 60
        slots = [slot for slot in slots
                 if (slot.end - slot.start).total_seconds() >= required]
    return slots