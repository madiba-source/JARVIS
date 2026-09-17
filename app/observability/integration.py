"""Event-bus observer connecting sanitized events to local sinks."""

from __future__ import annotations

from .events import StructuredEvent
from .enums import EventType
from .logging import StructuredLogger, event_to_dict
from .metrics import MetricsRegistry
from .redaction import redact_sensitive_data
from .store import SQLiteEventStore
from .tracing import LocalTracer, NullTracer


class ObservabilityAdapter:
    def __init__(self, logger: StructuredLogger, metrics: MetricsRegistry, tracer: LocalTracer | NullTracer, store: SQLiteEventStore) -> None:
        self.logger, self.metrics, self.tracer, self.store = logger, metrics, tracer, store
        self.failures = 0

    def attach(self, event_bus: object) -> None:
        event_bus.subscribe(self.handle_bus_event)

    def handle_bus_event(self, payload: object) -> None:
        if isinstance(payload, StructuredEvent):
            self.handle(payload)
            return
        if isinstance(payload, dict) and payload.get("event_type"):
            self.handle(StructuredEvent(event_type=EventType(payload["event_type"]), component=str(payload.get("component", "core")), source="event_bus"))

    def handle(self, event: StructuredEvent) -> None:
        safe = redact_sensitive_data(event_to_dict(event))
        if not self.logger.emit(event, safe): self.failures += 1
        try: self.metrics.increment_counter("observability_events_total", labels={"event_type": event.event_type.value})
        except ValueError: self.failures += 1
        if not self.store.store_event(event, safe): self.failures += 1
