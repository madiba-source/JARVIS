"""Bounded local performance and resource measurements."""

from __future__ import annotations

import os
import resource
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator

from .redaction import redact_sensitive_data


class TelemetryMode(StrEnum):
    OFF = "off"
    LOCAL = "local"
    DEBUG = "debug"


@dataclass(frozen=True)
class PerformanceBudget:
    max_samples_per_operation: int = 256
    max_operations: int = 64
    max_event_bytes: int = 2048

    def __post_init__(self) -> None:
        if min(self.max_samples_per_operation, self.max_operations, self.max_event_bytes) <= 0:
            raise ValueError("performance budgets must be positive")


@dataclass(frozen=True)
class ResourceSnapshot:
    rss_mb: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    thread_count: int
    process_id: int


@dataclass(frozen=True)
class PerformanceSample:
    operation: str
    duration_ms: float
    resource_before: ResourceSnapshot
    resource_after: ResourceSnapshot
    correlation: dict[str, str]


class PerformanceRecorder:
    def __init__(self, *, mode: TelemetryMode = TelemetryMode.LOCAL, budget: PerformanceBudget | None = None) -> None:
        self.mode = mode
        self.budget = budget or PerformanceBudget()
        self._samples: dict[str, list[PerformanceSample]] = defaultdict(list)
        self._lock = threading.Lock()

    @property
    def samples(self) -> dict[str, tuple[PerformanceSample, ...]]:
        with self._lock:
            return {key: tuple(values) for key, values in self._samples.items()}

    @staticmethod
    def snapshot() -> ResourceSnapshot:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return ResourceSnapshot(round(usage.ru_maxrss / 1024, 3), usage.ru_utime, usage.ru_stime, threading.active_count(), os.getpid())

    @contextmanager
    def measure(self, operation: str, *, correlation: dict[str, str] | None = None) -> Iterator[dict[str, float]]:
        if not operation or len(operation) > 64 or not operation.replace("_", "").replace(".", "").isalnum():
            raise ValueError("invalid performance operation")
        if self.mode is TelemetryMode.OFF:
            yield {}
            return
        before = self.snapshot()
        started = time.monotonic()
        result: dict[str, float] = {}
        try:
            yield result
        finally:
            duration = round((time.monotonic() - started) * 1000, 3)
            after = self.snapshot()
            safe_correlation = {key: str(value)[:64] for key, value in (correlation or {}).items() if key in {"session_id", "request_id", "task_id", "goal_id", "plan_id", "step_id", "trace_id", "tool_call_id"}}
            sample = PerformanceSample(operation, duration, before, after, redact_sensitive_data(safe_correlation))
            with self._lock:
                if operation in self._samples or len(self._samples) < self.budget.max_operations:
                    values = self._samples[operation]
                    values.append(sample)
                    del values[:-self.budget.max_samples_per_operation]
                result.update({"duration_ms": duration, "rss_mb": after.rss_mb})

    def summary(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {operation: {"count": len(values), "min_ms": min(item.duration_ms for item in values), "max_ms": max(item.duration_ms for item in values), "avg_ms": sum(item.duration_ms for item in values) / len(values)} for operation, values in self._samples.items() if values}

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def disable(self) -> None:
        self.mode = TelemetryMode.OFF
