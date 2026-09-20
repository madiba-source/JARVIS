from datetime import datetime, timedelta, timezone

import pytest

from app.agent.autonomy import (
    AutonomyLevel,
    AutonomousCoordinator,
    GoalError,
    GoalStatus,
    checkpoint,
    step_identity,
)
from app.agent.models import AgentResult, State


class FakeRuntime:
    def __init__(self, state=State.COMPLETED):
        self.state = state
        self.paused = False
        self.cancelled = False

    def submit(self, request, confirmations=None):
        return AgentResult(request_id=request.request_id, status=self.state, output="password=private")

    def cancel(self):
        self.cancelled = True
        return True

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


def test_goal_lifecycle_delegates_to_existing_agent_runtime():
    runtime = FakeRuntime()
    coordinator = AutonomousCoordinator(runtime, max_goals=1)
    goal = coordinator.create("inspect my workspace", session_id="session")
    result = coordinator.run(goal.goal_id, session_id="session")
    assert result.status is State.COMPLETED
    assert goal.status is GoalStatus.COMPLETED
    assert goal.progress == 100
    assert coordinator.checkpoints[goal.goal_id].observations == ()


def test_goal_limits_and_unrestricted_autonomy_fail_closed():
    coordinator = AutonomousCoordinator(FakeRuntime(), max_goals=1)
    coordinator.create("one", session_id="session")
    with pytest.raises(GoalError, match="capacity"):
        coordinator.create("two", session_id="session")
    with pytest.raises(GoalError, match="unrestricted"):
        AutonomousCoordinator(FakeRuntime()).create("privileged", session_id="session", autonomy=AutonomyLevel.A4)


def test_expired_goal_cannot_run():
    coordinator = AutonomousCoordinator(FakeRuntime())
    goal = coordinator.create("inspect", session_id="session")
    goal.deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(GoalError, match="expired"):
        coordinator.run(goal.goal_id, session_id="session")
    assert goal.status is GoalStatus.EXPIRED


def test_pause_resume_cancel_preserve_goal_control():
    runtime = FakeRuntime()
    coordinator = AutonomousCoordinator(runtime)
    goal = coordinator.create("inspect", session_id="session")
    coordinator.pause(goal.goal_id)
    assert goal.status is GoalStatus.PAUSED and runtime.paused
    coordinator.resume(goal.goal_id)
    assert goal.status is GoalStatus.RUNNING and not runtime.paused
    assert coordinator.cancel(goal.goal_id)
    assert goal.status is GoalStatus.CANCELLED and runtime.cancelled


def test_checkpoint_is_bounded_and_redacts_secrets():
    coordinator = AutonomousCoordinator(FakeRuntime())
    goal = coordinator.create("inspect", session_id="session")
    saved = checkpoint(goal, pending_steps=("step",), observations=("token=private-value", "safe"))
    assert saved.observations == ("token=[redacted]", "safe")
    assert step_identity(goal.goal_id, "request", "plan", "step", 1).endswith(":v1")
