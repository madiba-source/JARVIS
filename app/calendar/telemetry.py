"""Content-free calendar telemetry. Event payloads never include user content."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.events import EventBus

_BUILD = 8


def emit_calendar_event(
    bus: EventBus | None,
    event_type: str,
    *,
    success: bool | None = None,
    error_type: str = "",
    count: int = 0,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Publish a bounded, content-free calendar event. Never raises."""
    if bus is None:
        return
    payload: dict[str, Any] = {"event_type": event_type, "component": "calendar"}
    if success is not None:
        payload["success"] = success
    if error_type:
        payload["error_type"] = error_type[:_BUILD]
    if count:
        payload["count"] = int(count)
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 3)
    for key, value in (extra or {}).items():
        if isinstance(value, (bool, int, float, str)) and len(str(value)) <= 128:
            payload[key] = value
    try:
        bus.publish(payload)
    except Exception:
        pass


class _EmitLock(threading.local):
    busy = False


def _rate_limited(interval_seconds: float):
    """Throttle per-thread to guard against hot loops."""

    def decorator(func):
        last = threading.local()

        def wrapper(*args, **kwargs):
            now = time.monotonic()
            if not hasattr(last, "t"):
                last.t = 0.0
            if now - last.t >= interval_seconds:
                last.t = now
                return func(*args, **kwargs)
            return None

        return wrapper

    return decorator