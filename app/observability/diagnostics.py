"""Safe subsystem diagnostics without environment or payload dumps."""

from __future__ import annotations

import shutil
from typing import Any

from .config import ObservabilityConfig
from .logging import StructuredLogger
from .metrics import MetricsRegistry
from .store import SQLiteEventStore
from .tracing import LocalTracer, NullTracer


class DiagnosticsCollector:
    def __init__(self, config: ObservabilityConfig | None = None, logger: StructuredLogger | None = None, metrics: MetricsRegistry | None = None, tracer: LocalTracer | NullTracer | None = None, store: SQLiteEventStore | None = None) -> None:
        self.config = config or ObservabilityConfig()
        self.logger = logger or StructuredLogger(self.config)
        self.metrics = metrics or MetricsRegistry(self.config)
        self.tracer = tracer or (LocalTracer(self.config) if self.config.tracing_enabled else NullTracer())
        self.store = store or SQLiteEventStore(self.config)

    def collect(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.config.log_directory or ".")
        return {"logging": "ok" if self.logger.handler_count or not self.config.console_logging else "degraded", "metrics": "ok" if self.config.metrics_enabled else "disabled", "tracing": "ok" if self.config.tracing_enabled else "disabled", "sqlite": self.store.health(), "queue_depth": 0, "dropped_events": self.logger.dropped_events_count, "observability_failures": 0, "metric_series": self.metrics.series_count, "trace_count": self.tracer.trace_count if isinstance(self.tracer, LocalTracer) else 0, "disk_free_bytes": disk.free}
