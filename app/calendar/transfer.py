"""Bounded iCalendar transfer for calendar events.

The parser accepts only the small VEVENT subset JARVIS exports. It does not
execute content, follow URLs, or treat imported text as authorization.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import CalendarConfig
from .models import CalendarEvent


class CalendarTransferError(ValueError):
    pass


def export_ics(events: list[CalendarEvent], config: CalendarConfig) -> bytes:
    if len(events) > config.max_ics_events:
        raise CalendarTransferError("calendar export exceeds event limit")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//Calendar//EN"]
    for event in events:
        if event.all_day or event.start is None or event.end is None:
            continue
        lines.extend((
            "BEGIN:VEVENT",
            f"UID:{event.event_id}",
            f"DTSTART:{_format_dt(event.start)}",
            f"DTEND:{_format_dt(event.end)}",
            f"SUMMARY:{_escape(event.title)}",
            f"DESCRIPTION:{_escape(event.description)}",
            "END:VEVENT",
        ))
    lines.append("END:VCALENDAR")
    result = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    if len(result) > config.max_ics_bytes:
        raise CalendarTransferError("calendar export exceeds byte limit")
    return result


def import_ics(payload: bytes, config: CalendarConfig) -> list[CalendarEvent]:
    if len(payload) > config.max_ics_bytes:
        raise CalendarTransferError("calendar import exceeds byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CalendarTransferError("calendar import is not UTF-8") from error
    events: list[CalendarEvent] = []
    current: dict[str, str] | None = None
    for raw in text.replace("\r\n", "\n").splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise CalendarTransferError("nested calendar event")
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None:
                raise CalendarTransferError("calendar event terminator without event")
            try:
                events.append(CalendarEvent(
                    title=_required(current, "SUMMARY"),
                    description=current.get("DESCRIPTION", ""),
                    start=_parse_dt(_required(current, "DTSTART")),
                    end=_parse_dt(_required(current, "DTEND")),
                    source="icalendar",
                ))
            except (KeyError, ValueError) as error:
                raise CalendarTransferError("invalid calendar event") from error
            if len(events) > config.max_ics_events:
                raise CalendarTransferError("calendar import exceeds event limit")
            current = None
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0].upper()] = _unescape(value)
    if current is not None or not events:
        raise CalendarTransferError("calendar import contains no complete events")
    return events


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_dt(value: str) -> datetime:
    if not value.endswith("Z"):
        raise CalendarTransferError("calendar datetime must be UTC")
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise CalendarTransferError(f"missing {key}")
    return value