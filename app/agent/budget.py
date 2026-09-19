"""Deterministic consumption of bounded runtime budgets.

This is admission control, not operating-system enforcement: it refuses to start
or continue work once a bound is reached, and it stops rather than continuing
ungoverned. It never claims to cap CPU or memory use of a callback.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .config import AgentConfig
from .errors import BudgetExceeded, RuntimeDeadlineExceeded


class BudgetTracker:
    """One tracker per request; every counter is consumed, never inferred."""

    def __init__(self, config: AgentConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._lock = threading.RLock()
        self._started = clock()
        self._steps = 0
        self._side_effects = 0
        self._retries = 0
        self._replans = 0
        self._output_bytes = 0
        self._context_bytes = 0
        self._model_tokens = 0
        self._exhausted = ""

    @property
    def deadline(self) -> float:
        return self._started + self._config.max_runtime_seconds

    @property
    def exhausted_reason(self) -> str:
        with self._lock:
            return self._exhausted

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started)

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def _fail(self, reason: str, error: type[BudgetExceeded] = BudgetExceeded) -> None:
        with self._lock:
            self._exhausted = self._exhausted or reason
            recorded = self._exhausted
        raise error(recorded)

    def check_deadline(self) -> None:
        if self._clock() >= self.deadline:
            self._fail("runtime deadline exceeded", RuntimeDeadlineExceeded)

    def consume_step(self) -> int:
        self.check_deadline()
        with self._lock:
            self._steps += 1
            if self._steps > self._config.max_total_steps:
                self._exhausted = self._exhausted or "total step budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._steps

    def consume_side_effect(self) -> int:
        with self._lock:
            self._side_effects += 1
            if self._side_effects > self._config.max_side_effects:
                self._exhausted = self._exhausted or "side effect budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._side_effects

    def consume_retry(self) -> int:
        with self._lock:
            self._retries += 1
            if self._retries > self._config.max_retries * self._config.max_plan_steps:
                self._exhausted = self._exhausted or "retry budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._retries

    def consume_replan(self) -> int:
        with self._lock:
            self._replans += 1
            if self._replans > self._config.max_replans:
                self._exhausted = self._exhausted or "replan budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._replans

    def add_output_bytes(self, size: int) -> int:
        with self._lock:
            self._output_bytes += max(0, int(size))
            if self._output_bytes > self._config.max_output_bytes * self._config.max_plan_steps:
                self._exhausted = self._exhausted or "output budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._output_bytes

    def add_context_bytes(self, size: int) -> int:
        with self._lock:
            self._context_bytes += max(0, int(size))
            if self._context_bytes > self._config.max_context_bytes * (1 + self._config.max_replans):
                self._exhausted = self._exhausted or "context budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._context_bytes

    def add_model_tokens(self, tokens: int) -> int:
        with self._lock:
            self._model_tokens += max(0, int(tokens))
            ceiling = self._config.max_model_output_tokens * (2 + self._config.max_replans)
            if self._model_tokens > ceiling:
                self._exhausted = self._exhausted or "model token budget exceeded"
                raise BudgetExceeded(self._exhausted)
            return self._model_tokens

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "steps": float(self._steps),
                "side_effects": float(self._side_effects),
                "retries": float(self._retries),
                "replans": float(self._replans),
                "output_bytes": float(self._output_bytes),
                "context_bytes": float(self._context_bytes),
                "model_tokens": float(self._model_tokens),
                "elapsed_seconds": round(self.elapsed_seconds(), 3),
            }
