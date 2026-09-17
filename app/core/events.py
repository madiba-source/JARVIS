"""Small application event bus used by observability adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self, max_subscribers: int = 32) -> None:
        self._subscribers: list[Callable[[Any], None]] = []
        self._max = max_subscribers
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[Any], None]) -> None:
        with self._lock:
            if len(self._subscribers) >= self._max:
                raise ValueError("event subscriber limit reached")
            self._subscribers.append(callback)

    def publish(self, event: Any) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                continue
