"""Calendar, timetable and personal workflow subsystem.

Content is never authority: every mutation is validated against typed,
bounded schemas before it reaches this package.
"""

from app.calendar.config import CalendarConfig
from app.calendar.runtime import CalendarRuntime

__all__ = ["CalendarConfig", "CalendarRuntime"]