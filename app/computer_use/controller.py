"""Computer-use safety controller; it validates intent but owns no input driver."""

from __future__ import annotations

import threading
from typing import Any

from .models import ComputerAction, ComputerActionKind


class EmergencyStop(RuntimeError):
    pass


class ComputerUseController:
    def __init__(self, executor: Any = None, *, max_actions: int = 32) -> None:
        self._executor = executor
        self._max_actions = max(1, min(int(max_actions), 128))
        self._actions = 0
        self._stopped = False
        self._lock = threading.RLock()

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
        cancel = getattr(self._executor, "cancel", None)
        if callable(cancel):
            cancel()

    def execute(self, action: ComputerAction, *, current_observation_id: str) -> Any:
        with self._lock:
            if self._stopped:
                raise EmergencyStop("computer use stopped")
            if self._actions >= self._max_actions:
                raise EmergencyStop("computer action limit reached")
            self._actions += 1
        if action.kind in {ComputerActionKind.CLICK, ComputerActionKind.DOUBLE_CLICK, ComputerActionKind.MOVE_POINTER}:
            if action.target is None or action.target.observation_id != current_observation_id:
                raise ValueError("stale observation")
            if action.target.x >= action.target.image_width or action.target.y >= action.target.image_height:
                raise ValueError("coordinate outside observation")
        if self._executor is None:
            raise RuntimeError("computer input provider unavailable")
        return self._executor.execute(action)

    def reset(self) -> None:
        with self._lock:
            self._actions = 0
            self._stopped = False