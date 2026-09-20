"""Bounded long-horizon goals built on the existing AgentRuntime authority."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .models import AgentPlan, AgentRequest, AgentResult, Source, State
from .plan_validation import ValidatedPlan, validate_plan


class GoalStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    PAUSED = "paused"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AutonomyLevel(StrEnum):
    A0 = "a0"
    A1 = "a1"
    A2 = "a2"
    A3 = "a3"
    A4 = "a4"


@dataclass
class Goal:
    user_request: str
    deadline: datetime
    priority: str = "normal"
    constraints: tuple[str, ...] = ()
    required_confirmation: bool = False
    resource_budget: dict[str, int | float] = field(default_factory=dict)
    goal_id: str = field(default_factory=lambda: uuid4().hex)
    status: GoalStatus = GoalStatus.CREATED
    task_steps: tuple[str, ...] = ()
    current_step: str | None = None
    progress: int = 0
    cancellation_requested: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_steps: tuple[str, ...] = ()

    def expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.deadline

    def transition(self, status: GoalStatus) -> None:
        self.status = status
        if status == GoalStatus.EXPIRED:
            self.cancellation_requested = True


@dataclass(frozen=True)
class Checkpoint:
    goal_id: str
    status: GoalStatus
    completed_steps: tuple[str, ...]
    pending_steps: tuple[str, ...]
    observations: tuple[str, ...]
    confirmation_ids: tuple[str, ...] = ()
    retry_counters: dict[str, int] = field(default_factory=dict)
    resource_state: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class GoalProgress:
    goal_id: str
    status: GoalStatus
    current_step: str | None
    completed_steps: tuple[str, ...]
    remaining_steps: tuple[str, ...]
    blocked_steps: tuple[str, ...]
    elapsed_seconds: float


class GoalError(ValueError):
    pass


def validate_goal_plan(plan: AgentPlan, runtime: Any) -> ValidatedPlan:
    """Run the canonical agent plan validator before any execution."""
    return validate_plan(plan, runtime.planner.gateway.catalog, runtime.config)


def step_identity(goal_id: str, request_id: str, plan_id: str, step_id: str, version: int) -> str:
    return f"{goal_id}:{request_id}:{plan_id}:{step_id}:v{version}"


def checkpoint(goal: Goal, *, pending_steps: tuple[str, ...], observations: tuple[str, ...], confirmations: tuple[str, ...] = (), retries: dict[str, int] | None = None, resources: dict[str, float] | None = None) -> Checkpoint:
    bounded_observations = tuple(_safe_observation(value) for value in observations[-32:])
    return Checkpoint(goal.goal_id, goal.status, goal.completed_steps[-64:], pending_steps[:64], bounded_observations, confirmations[:16], dict(list((retries or {}).items())[:64]), dict(list((resources or {}).items())[:32]))


def _safe_observation(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)(password|token|secret|api[_ -]?key)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    return "".join(char for char in text if char.isprintable() or char == " ")[:512]


class AutonomousCoordinator:
    """Goal facade; planning, policy, tools, and execution remain AgentRuntime-owned."""

    def __init__(self, runtime: Any, *, max_goals: int = 8, max_goal_seconds: float = 3600) -> None:
        if max_goals <= 0 or max_goal_seconds <= 0:
            raise ValueError("goal limits must be positive")
        self.runtime = runtime
        self.max_goals = max_goals
        self.max_goal_seconds = max_goal_seconds
        self.goals: dict[str, Goal] = {}
        self.checkpoints: dict[str, Checkpoint] = {}

    def create(self, user_request: str, *, session_id: str, deadline: datetime | None = None, priority: str = "normal", constraints: tuple[str, ...] = (), autonomy: AutonomyLevel = AutonomyLevel.A1) -> Goal:
        if len(self.goals) >= self.max_goals:
            raise GoalError("goal capacity is full")
        if not user_request.strip() or len(user_request) > 4096:
            raise GoalError("goal request is invalid")
        if autonomy == AutonomyLevel.A4:
            raise GoalError("unrestricted autonomy is not available")
        end = deadline or datetime.now(timezone.utc) + timedelta(seconds=self.max_goal_seconds)
        if end <= datetime.now(timezone.utc) or end > datetime.now(timezone.utc) + timedelta(seconds=self.max_goal_seconds):
            raise GoalError("goal deadline exceeds the configured bound")
        goal = Goal(user_request=user_request, deadline=end, priority=priority, constraints=constraints, required_confirmation=autonomy in {AutonomyLevel.A3, AutonomyLevel.A4})
        self.goals[goal.goal_id] = goal
        return goal

    def run(self, goal_id: str, *, session_id: str, source: Source = Source.CLI, confirmations: Any = None) -> AgentResult:
        goal = self._get(goal_id)
        if goal.expired():
            goal.transition(GoalStatus.EXPIRED)
            raise GoalError("goal expired before execution")
        goal.transition(GoalStatus.RUNNING)
        request = AgentRequest(session_id=session_id, user_input=goal.user_request, source=source)
        started = time.monotonic()
        result = self.runtime.submit(request, confirmations=confirmations)
        goal.current_step = result.failed_step
        goal.status = self._status_for(result.status)
        if goal.status == GoalStatus.COMPLETED:
            goal.progress = 100
        self.checkpoints[goal.goal_id] = checkpoint(goal, pending_steps=(), observations=tuple(item.observation.summary for item in result.observations), resources={"elapsed_seconds": time.monotonic() - started})
        return result

    def cancel(self, goal_id: str) -> bool:
        goal = self._get(goal_id)
        goal.cancellation_requested = True
        goal.transition(GoalStatus.CANCELLED)
        return self.runtime.cancel()

    def pause(self, goal_id: str) -> None:
        goal = self._get(goal_id)
        goal.transition(GoalStatus.PAUSED)
        self.runtime.pause()

    def resume(self, goal_id: str) -> None:
        goal = self._get(goal_id)
        if goal.status != GoalStatus.PAUSED:
            raise GoalError("goal is not paused")
        goal.transition(GoalStatus.RUNNING)
        self.runtime.resume()

    def progress(self, goal_id: str) -> GoalProgress:
        goal = self._get(goal_id)
        checkpoint_data = self.checkpoints.get(goal_id)
        completed = checkpoint_data.completed_steps if checkpoint_data else goal.completed_steps
        remaining = checkpoint_data.pending_steps if checkpoint_data else goal.task_steps
        return GoalProgress(goal_id, goal.status, goal.current_step, completed, remaining, (), (datetime.now(timezone.utc) - goal.created_at).total_seconds())

    def _get(self, goal_id: str) -> Goal:
        try:
            return self.goals[goal_id]
        except KeyError:
            raise GoalError("unknown goal") from None

    @staticmethod
    def _status_for(state: State) -> GoalStatus:
        return {State.COMPLETED: GoalStatus.COMPLETED, State.CANCELLED: GoalStatus.CANCELLED, State.DISABLED: GoalStatus.CANCELLED, State.AWAITING_CONFIRMATION: GoalStatus.WAITING_FOR_CONFIRMATION, State.TIMED_OUT: GoalStatus.FAILED}.get(state, GoalStatus.FAILED)
