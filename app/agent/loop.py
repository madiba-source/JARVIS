"""Bounded loop detection.

A plan that keeps failing the same way, or keeps re-observing the same result,
must stop rather than run until a budget expires. Detection is deterministic: it
keys on the tool, operation, canonical arguments and the failure code.
"""

from __future__ import annotations

import hashlib
from collections import deque

from .config import AgentConfig
from .errors import LoopDetected
from .models import Observation

MAX_TRACKED_SIGNATURES = 64
MAX_RECENT = 32


class LoopDetector:
    """Counts materially identical failures for one request."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._failures: dict[str, int] = {}
        self._recent: deque[str] = deque(maxlen=MAX_RECENT)

    @staticmethod
    def signature(tool_id: str, operation: str, arguments_json: str) -> str:
        digest = hashlib.sha256(f"{tool_id}\x1f{operation}\x1f{arguments_json}".encode("utf-8"))
        return digest.hexdigest()[:32]

    def record(self, signature: str, observation: Observation) -> None:
        """Record a finished attempt. Raises `LoopDetected` on repetition."""
        key = f"{signature}:{observation.code}"
        self._recent.append(key)
        count = self._failures.get(key, 0) + 1
        if len(self._failures) >= MAX_TRACKED_SIGNATURES and key not in self._failures:
            self._failures.clear()
        self._failures[key] = count
        if count >= self._config.max_identical_failures:
            raise LoopDetected("identical failures repeated")

    def forget(self, signature: str) -> None:
        for key in [item for item in self._failures if item.startswith(f"{signature}:")]:
            self._failures.pop(key, None)

    @property
    def recent(self) -> tuple[str, ...]:
        return tuple(self._recent)

    def describe(self) -> dict[str, int]:
        return {"tracked": len(self._failures), "recent": len(self._recent)}
