"""Public Phase 06 agent runtime interfaces."""

from .events import AgentEvent, AgentEventType
from .models import AgentPlan, AgentRequest, AgentResult, AgentSession, AgentStep
from .autonomy import AutonomyLevel, AutonomousCoordinator, Goal, GoalStatus


def __getattr__(name: str):
    if name == "AgentRuntime":
        from .coordinator import AgentRuntime
        return AgentRuntime
    raise AttributeError(name)

__all__ = [
    "AgentEvent", "AgentEventType", "AgentPlan", "AgentRequest", "AgentResult",
    "AgentRuntime", "AgentSession", "AgentStep",
    "AutonomyLevel", "AutonomousCoordinator", "Goal", "GoalStatus",
]