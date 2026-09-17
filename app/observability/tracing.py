"""Bounded local tracing adapter with context restoration."""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import ObservabilityConfig
from .ids import generate_span_id, generate_trace_id
from .redaction import redact_sensitive_data


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    _max_attributes: int = 32
    _max_events: int = 32
    _max_value_bytes: int = 2048
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        if len(self.attributes) >= self._max_attributes and key not in self.attributes:
            return
        safe = redact_sensitive_data(value)
        if len(str(safe).encode()) <= self._max_value_bytes:
            self.attributes[key] = safe

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        if len(self.events) < self._max_events:
            self.events.append({"name": name, "attributes": redact_sensitive_data(attributes or {})})


class TracerProtocol(Protocol):
    def start_span(self, name: str) -> "SpanContext": ...


class SpanContext(AbstractContextManager[Span]):
    def __init__(self, tracer: "LocalTracer", span: Span, previous: tuple[str | None, str | None]) -> None:
        self.tracer, self.span, self.previous = tracer, span, previous

    def __enter__(self) -> Span:
        return self.span

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tracer.finish_span(self.span, self.previous)


class NullTracer:
    def start_span(self, name: str, **kwargs: Any) -> SpanContext:
        return SpanContext(self, Span(name, "", ""), (None, None))

    def finish_span(self, span: Span, previous: tuple[str | None, str | None] = (None, None)) -> None:
        return None


class LocalTracer:
    def __init__(self, config: ObservabilityConfig | None = None) -> None:
        self.config = config or ObservabilityConfig()
        self._local = threading.local()
        self._completed_traces: dict[str, list[Span]] = {}
        self._lock = threading.Lock()
        self._rejected = 0

    def start_span(self, name: str, trace_id: str | None = None, parent_span_id: str | None = None) -> SpanContext:
        current_trace = getattr(self._local, "trace_id", None)
        current_span = getattr(self._local, "span_id", None)
        trace = trace_id or current_trace or generate_trace_id()
        span = Span(name, trace, generate_span_id(), parent_span_id or current_span, self.config.max_span_attributes, self.config.max_span_events, self.config.max_attribute_value_bytes)
        self._local.trace_id, self._local.span_id = trace, span.span_id
        return SpanContext(self, span, (current_trace, current_span))

    def finish_span(self, span: Span, previous: tuple[str | None, str | None] = (None, None)) -> None:
        with self._lock:
            if span.trace_id not in self._completed_traces and len(self._completed_traces) >= self.config.max_trace_count:
                oldest = next(iter(self._completed_traces)); self._completed_traces.pop(oldest); self._rejected += 1
            trace = self._completed_traces.setdefault(span.trace_id, [])
            if len(trace) < self.config.max_spans_per_trace:
                trace.append(span)
        self._local.trace_id, self._local.span_id = previous

    def completed_trace(self, trace_id: str) -> list[Span]:
        with self._lock:
            return list(self._completed_traces.get(trace_id, []))

    @property
    def trace_count(self) -> int:
        with self._lock:
            return len(self._completed_traces)
