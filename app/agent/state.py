"""Explicit agent state machine.

Transitions are declared, not implied. Control changes (cancel, disable,
timeout) are allowed from any non-terminal state and are the only way to leave
an execution state unexpectedly. Pause is *not* a state: it is an orthogonal
control flag handled by `AgentControl`, so a paused plan keeps its identity and
its completed steps.
"""

from __future__ import annotations

import threading
from collections import deque

from .models import State

TERMINAL = frozenset({State.COMPLETED, State.FAILED, State.CANCELLED, State.DISABLED, State.TIMED_OUT})
_CONTROL = frozenset({State.FAILED, State.CANCELLED, State.DISABLED, State.TIMED_OUT})
_EDGES: dict[State, frozenset[State]] = {
    State.IDLE: frozenset({State.RECEIVED}),
    State.RECEIVED: frozenset({State.PLANNING}),
    State.PLANNING: frozenset({State.EXECUTING, State.AWAITING_CONFIRMATION}),
    State.AWAITING_CONFIRMATION: frozenset({State.EXECUTING}),
    State.EXECUTING: frozenset({State.OBSERVING, State.AWAITING_CONFIRMATION}),
    State.OBSERVING: frozenset({State.VERIFYING}),
    State.VERIFYING: frozenset({State.EXECUTING, State.RECOVERING, State.COMPLETED}),
    State.RECOVERING: frozenset({State.EXECUTING, State.PLANNING}),
}

MAX_HISTORY = 32


def settle_override(target: State) -> bool:
    """True when a target is a permitted control override."""
    return target in _CONTROL


def canonical_state(value: object) -> State:
    """Accept a State or its string form; reject anything else."""
    if isinstance(value, State):
        return value
    if isinstance(value, str):
        try:
            return State(value)
        except ValueError:
            raise ValueError("unknown agent state") from None
    raise ValueError("unknown agent state")


def transition(current: State, target: State) -> State:
    """Return the next state, or raise `ValueError` for an invalid move."""
    current = canonical_state(current)
    target = canonical_state(target)
    if current in TERMINAL:
        raise ValueError("terminal state cannot transition")
    if settle_override(target):
        return target
    if target not in _EDGES.get(current, frozenset()):
        raise ValueError("invalid agent state transition")
    return target


def allowed_targets(current: State) -> tuple[State, ...]:
    current = canonical_state(current)
    if current in TERMINAL:
        return ()
    return tuple(sorted(_EDGES.get(current, frozenset()) | _CONTROL, key=lambda item: item.value))


class StateMachine:
    """Thread-safe tracker that enforces the declared transition graph."""

    def __init__(self, initial: State = State.IDLE, keep_history: bool = True) -> None:
        self._lock = threading.RLock()
        self._state = canonical_state(initial)
        self._history: deque[State] = deque(maxlen=MAX_HISTORY if keep_history else 1)
        self._history.append(self._state)

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def is_terminal(self) -> bool:
        with self._lock:
            return self._state in TERMINAL

    def to(self, target: State) -> State:
        with self._lock:
            self._state = transition(self._state, target)
            self._history.append(self._state)
            return self._state

    def can(self, target: State) -> bool:
        with self._lock:
            try:
                transition(self._state, target)
            except ValueError:
                return False
            return True

    def history(self) -> tuple[State, ...]:
        with self._lock:
            return tuple(self._history)

    def describe(self) -> dict[str, object]:
        with self._lock:
            return {"state": self._state.value, "terminal": self._state in TERMINAL}
