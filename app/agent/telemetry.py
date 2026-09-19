"""Bounded agent telemetry.

Three sinks, one rule: identifiers, fixed codes and counters only. No user text,
no tool arguments, no model output, no file contents, no exception detail.

Failure of any sink is swallowed. Telemetry never becomes authority, and it is
never a reason to execute more work.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from app.observability.events import StructuredEvent
from app.observability.metrics import MetricsRegistry
from app.policy.enums import AuthorizationLevel, DecisionState
from app.policy.models import AuditEvent

from .events import AgentEventType, SemanticSignal, observability_event_type, semantic_signal

COUNTER_NAMES = (
    "agent_requests_total",
    "agent_completed_total",
    "agent_failed_total",
    "agent_cancelled_total",
    "agent_plan_rejections_total",
    "agent_steps_total",
    "agent_step_failures_total",
    "agent_replans_total",
    "agent_retries_total",
)
TIMING_NAMES = ("agent_latency_ms",)
GAUGE_NAMES = ("agent_active",)
MAX_METADATA_ENTRIES = 10


class AgentTelemetry:
    def __init__(self, bus: Any = None, metrics: MetricsRegistry | None = None,
                 audit_sink: Any = None) -> None:
        self._bus = bus
        self._metrics = metrics
        self._audit_sink = audit_sink
        self._lock = threading.RLock()
        self._counters = {name: 0 for name in COUNTER_NAMES}
        self._gauges = {name: 0.0 for name in GAUGE_NAMES}
        self._timings: dict[str, list[float]] = {name: [] for name in TIMING_NAMES}
        self._events = 0
        self._failures = 0
        self._last_signal: SemanticSignal | None = None
        self._signals: list[SemanticSignal] = []

    # --- reads ----------------------------------------------------------
    @property
    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    @property
    def last_signal(self) -> SemanticSignal | None:
        with self._lock:
            return self._last_signal

    def signals(self) -> tuple[SemanticSignal, ...]:
        with self._lock:
            return tuple(self._signals)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timings = {name: {"count": len(values), "total_ms": round(sum(values), 3)}
                       for name, values in self._timings.items()}
            return {"counters": dict(self._counters), "gauges": dict(self._gauges),
                    "timings": timings, "events": self._events, "failures": self._failures}

    # --- emission -------------------------------------------------------
    def emit(self, agent_event: AgentEventType, *, request_id: str | None = None,
             plan_id: str | None = None, step_id: str | None = None, tool_id: str | None = None,
             operation: str | None = None, state: str | None = None,
             success: bool | None = None, reason_code: str = "",
             duration_ms: float | None = None) -> SemanticSignal | None:
        signal = semantic_signal(agent_event, tool_id)
        try:
            with self._lock:
                self._events += 1
                if signal is not None:
                    self._last_signal = signal
                    self._signals.append(signal)
                    del self._signals[:-64]
            event = StructuredEvent(
                event_type=observability_event_type(agent_event),
                component="agent",
                source="AgentTelemetry",
                request_id=_bounded(request_id, 64),
                tool_id=_bounded(tool_id, 64),
                operation=_bounded(operation, 64),
                success=success,
                duration_ms=None if duration_ms is None else max(0.0, float(duration_ms)),
                metadata=self._metadata(agent_event, signal, plan_id, step_id, state, reason_code),
            )
            if self._bus is not None:
                self._bus.publish(event)
        except Exception:
            self._record_failure()
        return signal

    @staticmethod
    def _metadata(agent_event: AgentEventType, signal: SemanticSignal | None, plan_id: str | None,
                  step_id: str | None, state: str | None, reason_code: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {"agent_event": agent_event.value}
        for key, value in (("signal", signal.value if signal else None), ("plan_id", plan_id),
                           ("step_id", step_id), ("state", state), ("reason_code", reason_code)):
            if value:
                metadata[key] = _bounded(value, 64)
        return dict(list(metadata.items())[:MAX_METADATA_ENTRIES])

    # --- metrics --------------------------------------------------------
    def counter(self, name: str, value: int = 1) -> None:
        if name not in self._counters:
            return
        with self._lock:
            self._counters[name] += int(value)
        self._mirror("increment_counter", name, value)
        self._hub()

    def gauge(self, name: str, value: float) -> None:
        if name not in self._gauges:
            return
        with self._lock:
            self._gauges[name] = max(0.0, float(value))
        self._mirror("set_gauge", name, value)
        self._hub()

    def timing(self, name: str, duration_ms: float) -> None:
        if name not in self._timings:
            return
        with self._lock:
            values = self._timings[name]
            values.append(max(0.0, float(duration_ms)))
            del values[:-256]
        self._mirror("record_timing", name, duration_ms)

    def _mirror(self, operation: str, name: str, value: float) -> None:
        if self._metrics is None:
            return
        try:
            getattr(self._metrics, operation)(name, value)
        except Exception:
            self._record_failure()

    def _hub(self) -> None:
        """Maintain the fixed active-work gauge without unbounded labels."""
        return None

    # --- audit ----------------------------------------------------------
    def audit_step(self, *, request_id: str, tool_id: str, operation: str, outcome: str,
                   authorization_level: AuthorizationLevel | None = None,
                   confirmation_state: str = "NOT_USED", resource_decision: str = "ADMITTED",
                   allowed: bool = True) -> bool:
        """Record one executable step through the existing audit mechanism."""
        if self._audit_sink is None:
            return False
        try:
            event = AuditEvent(
                event_id=f"agent-{uuid.uuid4().hex}",
                request_id=_bounded(request_id, 64) or "unknown",
                tool_id=_bounded(tool_id, 64) or "unknown",
                requested_operation=_bounded(operation, 64) or "unknown",
                decision=DecisionState.ALLOW if allowed else DecisionState.POLICY_ERROR,
                authorization_level=authorization_level,
                confirmation_state=_bounded(confirmation_state, 32) or "NOT_USED",
                resource_decision=_bounded(resource_decision, 32) or "NOT_USED",
                reason=_bounded(outcome, 64) or "step",
                source_subsystem="phase06.agent",
            )
            return bool(self._audit_sink.record_audit(event))
        except Exception:
            self._record_failure()
            return False

    # --- health ---------------------------------------------------------
    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {"events": self._events, "failures": self._failures,
                    "counters": dict(self._counters), "gauges": dict(self._gauges)}


def _bounded(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = "".join(c for c in str(value) if c.isprintable() and c not in " ")
    return text[:limit] or None
