"""Idempotency keys for step execution.

A key is `request_id + plan_id + step_id + plan_version`. It exists to stop the
runtime from accidentally executing the same authorized step twice, for example
if a scheduler retry and an operator resume overlap.

Crucially, a key never *authorizes* anything and never substitutes for a fresh
policy evaluation on a new plan version. A replan produces new keys, because a
replan is a new plan.
"""

from __future__ import annotations

import threading

from .errors import DuplicateExecution
from .models import Observation

MAX_KEYS = 128


class IdempotencyRegistry:
    """Single-flight claim registry for one request."""

    def __init__(self, capacity: int = MAX_KEYS) -> None:
        self._capacity = max(1, min(int(capacity), MAX_KEYS))
        self._lock = threading.RLock()
        self._in_flight: set[str] = set()
        self._order: list[str] = []
        self._recorded: dict[str, Observation] = {}

    @staticmethod
    def key(request_id: str, plan_id: str, step_id: str, version: int) -> str:
        return f"{request_id}:{plan_id}:{step_id}:v{int(version)}"

    def claim(self, key: str, *, allow_reentry: bool = False) -> bool:
        """Claim a key for execution. False when it is already complete."""
        with self._lock:
            if key in self._recorded:
                return False
            if key in self._in_flight:
                if not allow_reentry:
                    return False
                return True
            self._in_flight.add(key)
            self._order.append(key)
            self._evict()
            return True

    def begin(self, key: str, *, allow_reentry: bool = False) -> None:
        """Claim a key or raise `DuplicateExecution`."""
        if not self.claim(key, allow_reentry=allow_reentry):
            raise DuplicateExecution("step already completed or in flight")

    def release(self, key: str) -> None:
        with self._lock:
            self._in_flight.discard(key)

    def record(self, key: str, observation: Observation) -> None:
        with self._lock:
            self._in_flight.discard(key)
            self._recorded[key] = observation
            self._evict()

    def recorded(self, key: str) -> Observation | None:
        with self._lock:
            return self._recorded.get(key)

    def _evict(self) -> None:
        while len(self._order) > self._capacity:
            oldest = self._order.pop(0)
            self._in_flight.discard(oldest)
            self._recorded.pop(oldest, None)

    def describe(self) -> dict[str, int]:
        with self._lock:
            return {"in_flight": len(self._in_flight), "recorded": len(self._recorded)}
