"""Structured audit recording with conservative redaction."""

import re
import threading
from copy import deepcopy

from .models import AuditEvent


class AuditLogger:
    _sensitive = re.compile(r"(?:api[_-]?key|password|secret|token|authorization|credential|cookie)", re.IGNORECASE)

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
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
