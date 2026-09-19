"""Atomic JARVIS control state: the global enable/disable barrier.

This is the agent runtime's half of the deterministic disable mechanism. It is
deliberately the only place that decides whether agent work may start, and it
uses the same lock-and-generation discipline as the Phase 03 evaluator so that
a disable cannot race an admission.

Disabling JARVIS here:

* bumps a generation, so plans that began earlier abort at their next boundary;
* stops the runtime from accepting or starting executable work;
* cancels cooperative workflows through their cancellation tokens;
* hides nothing from the human: normal Kali operation is unaffected.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .errors import AgentCancelled, DisabledError, RuntimeDeadlineExceeded

MAX_LISTENERS = 32


class ControlState(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ControlSnapshot:
    state: ControlState
    generation: int

    @property
    def enabled(self) -> bool:
        return self.state is ControlState.ENABLED


class AgentControl:
    """Process-wide enable/pause state consulted by every execution path."""

    def __init__(self, state: ControlState = ControlState.ENABLED) -> None:
        self._lock = threading.RLock()
        self._state = state
        self._generation = 0
        self._listeners: list[Callable[[ControlSnapshot], None]] = []

    @property
    def state(self) -> ControlState:
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._state is ControlState.ENABLED

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._state is ControlState.PAUSED

    @property
    def disabled(self) -> bool:
        with self._lock:
            return self._state is ControlState.DISABLED

    def snapshot(self) -> ControlSnapshot:
        with self._lock:
            return ControlSnapshot(state=self._state, generation=self._generation)

    def subscribe(self, listener: Callable[[ControlSnapshot], None]) -> None:
        with self._lock:
            if len(self._listeners) >= MAX_LISTENERS:
                raise DisabledError("control listener limit reached")
            self._listeners.append(listener)

    def _publish(self, snapshot: ControlSnapshot) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                continue

    def _transition(self, state: ControlState, bump: bool) -> ControlSnapshot:
        with self._lock:
            previous = self._state
            if previous is state and not bump:
                return ControlSnapshot(state=state, generation=self._generation)
            self._state = state
            if bump:
                self._generation += 1
            snapshot = ControlSnapshot(state=state, generation=self._generation)
        self._publish(snapshot)
        return snapshot

    def disable(self) -> ControlSnapshot:
        """Stop all agent execution. Idempotent; always bumps the generation."""
        return self._transition(ControlState.DISABLED, bump=True)

    def enable(self) -> ControlSnapshot:
        """Allow execution again. Bumps only when leaving DISABLED."""
        with self._lock:
            leaving_disabled = self._state is ControlState.DISABLED
        return self._transition(ControlState.ENABLED, bump=leaving_disabled)

    def pause(self) -> ControlSnapshot:
        """Prevent new executable work. Running work may finish cooperatively."""
        with self._lock:
            if self._state is ControlState.DISABLED:
                raise DisabledError("cannot pause while disabled")
        return self._transition(ControlState.PAUSED, bump=False)

    def resume(self) -> ControlSnapshot:
        with self._lock:
            if self._state is ControlState.DISABLED:
                raise DisabledError("cannot resume while disabled")
        return self._transition(ControlState.ENABLED, bump=False)

    def require_enabled(self) -> ControlSnapshot:
        with self._lock:
            if self._state is ControlState.DISABLED:
                raise DisabledError("JARVIS is disabled")
            return ControlSnapshot(state=self._state, generation=self._generation)

    def require_current(self, generation: int) -> ControlSnapshot:
        """Reject work authorized under a superseded generation."""
        snapshot = self.require_enabled()
        if snapshot.generation != generation:
            raise DisabledError("execution invalidated by a JARVIS control change")
        return snapshot

    def wait_until_runnable(self, cancel: object | None, deadline: float | None,
                            interval: float = 0.05) -> None:
        """Block while paused. Raises on disable, cancellation or deadline."""
        while True:
            with self._lock:
                state = self._state
            if state is ControlState.DISABLED:
                raise DisabledError("JARVIS is disabled")
            if state is ControlState.ENABLED:
                return
            if cancel is not None and getattr(cancel, "is_cancelled", False):
                raise AgentCancelled("cancelled while paused")
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeDeadlineExceeded("runtime deadline exceeded while paused")
            time.sleep(interval)

    def describe(self) -> dict[str, object]:
        with self._lock:
            return {"state": self._state.value, "generation": self._generation}


_GLOBAL = AgentControl()


def get_global_control() -> AgentControl:
    return _GLOBAL


def reset_global_control() -> AgentControl:
    """Test/administration helper: replaces the process-wide control object."""
    global _GLOBAL
    _GLOBAL = AgentControl()
    return _GLOBAL
