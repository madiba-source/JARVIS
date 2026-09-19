"""Cooperative cancellation tokens.

Cancellation is never assumed to kill arbitrary work. It stops the runtime
from scheduling more work, and tells a cooperative tool to stop when it can.
When an underlying tool cannot be interrupted, the runtime records the step as
cancellation-pending instead of pretending the operation stopped.
"""

from __future__ import annotations

import threading

from .errors import AgentCancelled


class CancellationToken:
    """A cancellable flag with a bounded set of linked children."""

    def __init__(self, reason: str = "") -> None:
        self._event = threading.Event()
        self._reason = reason
        self._children: list[CancellationToken] = []
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> bool:
        """Signal cancellation. Returns True only on the first transition."""
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason
            self._event.set()
            children = tuple(self._children)
        for child in children:
            child.cancel(reason)
        return True

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise AgentCancelled(self._reason or "cancelled")

    def child(self) -> CancellationToken:
        """Create a linked token cancelled whenever this token is cancelled."""
        child = CancellationToken(self._reason)
        with self._lock:
            if self._event.is_set():
                child.cancel(self._reason or "cancelled")
            else:
                self._children.append(child)
        return child

    @classmethod
    def cancelled(cls, reason: str = "cancelled") -> CancellationToken:
        token = cls(reason)
        token.cancel(reason)
        return token
