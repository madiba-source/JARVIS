"""Thread-safe metrics with bounded series cardinality."""

from __future__ import annotations

import math
import re
import threading
from typing import Any

from .config import ObservabilityConfig


class MetricsRegistry:
    _name = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")

    def __init__(self, config: ObservabilityConfig | None = None, max_series: int | None = None) -> None:
        self.config = config or ObservabilityConfig()
        self._max_series = max_series or self.config.max_metric_series
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._rejected = 0

    def _key(self, name: str, labels: dict[str, str] | None) -> str:
        if not self._name.fullmatch(name):
            raise ValueError("invalid metric name")
        labels = labels or {}
        if len(labels) > self.config.max_metric_labels or any(not self._name.fullmatch(k) for k in labels):
            raise ValueError("invalid metric labels")
        if any(len(v) > 64 for v in labels.values()):
            raise ValueError("metric label value too long")
        return name + ("{" + ",".join(f"{k}={labels[k]}" for k in sorted(labels)) + "}" if labels else "")

    def _admit(self, key: str, collection: dict[str, Any]) -> None:
        known_series = set(self._counters) | set(self._gauges) | set(self._histograms)
        if key not in known_series and len(known_series) >= self._max_series:
            self._rejected += 1
            raise ValueError("metric series limit reached")

    def increment_counter(self, name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._admit(key, self._counters)
            self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        if not math.isfinite(value):
            raise ValueError("gauge must be finite")
        key = self._key(name, labels)
        with self._lock:
            self._admit(key, self._gauges)
            self._gauges[key] = value

    def record_timing(self, name: str, duration_ms: float, labels: dict[str, str] | None = None) -> None:
        if not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("timing must be finite and non-negative")
        key = self._key(name, labels)
        with self._lock:
            self._admit(key, self._histograms)
            samples = self._histograms.setdefault(key, [])
            samples.append(duration_ms)
            del samples[:-1000]

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges), "histograms": {key: {"count": len(values), "sum": sum(values), "avg": sum(values) / len(values)} for key, values in self._histograms.items()}, "rejected_series": self._rejected}

    @property
    def series_count(self) -> int:
        with self._lock:
            return len(set(self._counters) | set(self._gauges) | set(self._histograms))

    def clear(self) -> None:
        with self._lock:
            self._counters.clear(); self._gauges.clear(); self._histograms.clear(); self._rejected = 0
