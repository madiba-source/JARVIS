"""Structured audit recording with conservative redaction."""

import re
import threading
from collections import deque
from copy import deepcopy

from .models import AuditEvent


class AuditLogger:
    DEFAULT_MAX_EVENTS = 4096
    MAX_EVENTS = 100_000
    _sensitive = re.compile(r"(?:api[_-]?key|password|secret|token|authorization|credential|cookie)", re.IGNORECASE)

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= self.MAX_EVENTS:
            raise ValueError(f"max_events must be an integer between 1 and {self.MAX_EVENTS}")
        self.max_events = max_events
        self._events: deque[AuditEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    @classmethod
    def _sanitize(cls, value: str) -> str:
        return "[REDACTED_SENSITIVE_CONTENT]" if cls._sensitive.search(value) else value

    def record(self, event: AuditEvent) -> None:
        sanitized = event.model_copy(update={
            "requested_operation": self._sanitize(event.requested_operation),
            "reason": self._sanitize(event.reason),
            "source_subsystem": self._sanitize(event.source_subsystem),
        })
        with self._lock:
            self._events.append(sanitized)

    def get_events(self) -> list[AuditEvent]:
        with self._lock:
            return deepcopy(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
