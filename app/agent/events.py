"""Agent lifecycle event vocabulary and interface-signal projection.

Two vocabularies are kept deliberately separate:

* `AgentEventType` is the runtime's own contract. It is stable, dotted and
  bounded, and it is what the coordinator, audit and metrics agree on.
* `SemanticSignal` is the interface vocabulary that a future HUD and audio
  engine consume. Projecting lifecycle events onto signals here means the
  interface layer never has to know runtime internals, and this phase never
  has to know visual or audio design.

Neither vocabulary ever carries user text, tool arguments, model output or
filesystem contents. Only identifiers, fixed codes and small counters.
"""

from __future__ import annotations

from enum import StrEnum

from datetime import datetime
from pydantic import Field

from app.observability.enums import EventType
from .models import Identifier, Schema, now


class AgentEventType(StrEnum):
    REQUESTED = "agent.requested"
    PLANNING = "agent.planning"
    PLANNED = "agent.planned"
    PLAN_REJECTED = "agent.plan_rejected"
    AWAITING_CONFIRMATION = "agent.awaiting_confirmation"
    STARTED = "agent.started"
    STEP_STARTED = "agent.step_started"
    STEP_COMPLETED = "agent.step_completed"
    STEP_FAILED = "agent.step_failed"
    OBSERVED = "agent.observed"
    VERIFICATION_FAILED = "agent.verification_failed"
    REPLANNED = "agent.replanned"
    CANCELLED = "agent.cancelled"
    PAUSED = "agent.paused"
    RESUMED = "agent.resumed"
    COMPLETED = "agent.completed"
    FAILED = "agent.failed"
    DISABLED = "agent.disabled"


class AgentEvent(Schema):
    event_type: AgentEventType | str
    request_id: Identifier | None = None
    session_id: Identifier | None = None
    timestamp: datetime = Field(default_factory=now)
    state: str = Field(default="", max_length=32)
    reason_code: str = Field(default="", max_length=64)


class SemanticSignal(StrEnum):
    """Interface-level signals. No visual or audio asset is defined here."""

    SYSTEM_READY = "SYSTEM_READY"
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    PLANNING_STARTED = "PLANNING_STARTED"
    SCANNING = "SCANNING"
    PROCESSING = "PROCESSING"
    TOOL_OPENING = "TOOL_OPENING"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    VERIFICATION = "VERIFICATION"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    JARVIS_DISABLED = "JARVIS_DISABLED"


_OBSERVABILITY: dict[AgentEventType, EventType] = {
    AgentEventType.REQUESTED: EventType.REQUEST_RECEIVED,
    AgentEventType.PLANNING: EventType.AGENT_PLANNING,
    AgentEventType.PLANNED: EventType.AGENT_PLANNED,
    AgentEventType.PLAN_REJECTED: EventType.AGENT_PLAN_REJECTED,
    AgentEventType.AWAITING_CONFIRMATION: EventType.AGENT_AWAITING_CONFIRMATION,
    AgentEventType.STARTED: EventType.AGENT_STARTED,
    AgentEventType.STEP_STARTED: EventType.AGENT_STEP_STARTED,
    AgentEventType.STEP_COMPLETED: EventType.AGENT_STEP_COMPLETED,
    AgentEventType.STEP_FAILED: EventType.AGENT_STEP_FAILED,
    AgentEventType.OBSERVED: EventType.AGENT_OBSERVED,
    AgentEventType.VERIFICATION_FAILED: EventType.AGENT_VERIFICATION_FAILED,
    AgentEventType.REPLANNED: EventType.AGENT_REPLANNED,
    AgentEventType.CANCELLED: EventType.AGENT_CANCELLED,
    AgentEventType.PAUSED: EventType.AGENT_PAUSED,
    AgentEventType.RESUMED: EventType.AGENT_RESUMED,
    AgentEventType.COMPLETED: EventType.AGENT_COMPLETED,
    AgentEventType.FAILED: EventType.AGENT_FAILED,
    AgentEventType.DISABLED: EventType.AGENT_DISABLED,
}

# Tools whose start is an interface "opening" moment rather than a bare execution.
_OPENING_TOOLS = frozenset({"applications", "application_control", "application_terminate"})

_SEMANTIC: dict[AgentEventType, SemanticSignal] = {
    AgentEventType.REQUESTED: SemanticSignal.REQUEST_RECEIVED,
    AgentEventType.PLANNING: SemanticSignal.PLANNING_STARTED,
    AgentEventType.PLANNED: SemanticSignal.PROCESSING,
    AgentEventType.STARTED: SemanticSignal.SCANNING,
    AgentEventType.STEP_STARTED: SemanticSignal.TOOL_EXECUTING,
    AgentEventType.STEP_COMPLETED: SemanticSignal.PROCESSING,
    AgentEventType.STEP_FAILED: SemanticSignal.ERROR,
    AgentEventType.OBSERVED: SemanticSignal.PROCESSING,
    AgentEventType.VERIFICATION_FAILED: SemanticSignal.WARNING,
    AgentEventType.REPLANNED: SemanticSignal.SCANNING,
    AgentEventType.CANCELLED: SemanticSignal.CANCELLED,
    AgentEventType.PAUSED: SemanticSignal.WARNING,
    AgentEventType.RESUMED: SemanticSignal.PROCESSING,
    AgentEventType.COMPLETED: SemanticSignal.SUCCESS,
    AgentEventType.FAILED: SemanticSignal.ERROR,
    AgentEventType.DISABLED: SemanticSignal.JARVIS_DISABLED,
}


def observability_event_type(agent_event: AgentEventType) -> EventType:
    """Map a lifecycle event onto the shared observability enum."""
    return _OBSERVABILITY[agent_event]


def semantic_signal(agent_event: AgentEventType, tool_id: str | None = None) -> SemanticSignal | None:
    """Project a lifecycle event onto the interface/audio vocabulary."""
    if agent_event is AgentEventType.STEP_STARTED and tool_id in _OPENING_TOOLS:
        return SemanticSignal.TOOL_OPENING
    if agent_event is AgentEventType.PLAN_REJECTED:
        return SemanticSignal.ERROR
    if agent_event is AgentEventType.AWAITING_CONFIRMATION:
        return SemanticSignal.WARNING
    return _SEMANTIC.get(agent_event)


def known_agent_event_types() -> tuple[str, ...]:
    return tuple(item.value for item in AgentEventType)
