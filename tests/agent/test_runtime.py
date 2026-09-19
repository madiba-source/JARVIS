import json

from app.agent import AgentRequest, AgentRuntime
from app.agent.config import AgentConfig
from app.agent.providers import StaticProvider
from app.agent.router import ModelRouter
from app.policy.service import PolicyEngineService


def _runtime(plan: dict, *, cloud_enabled: bool = False) -> AgentRuntime:
    config = AgentConfig(cloud_enabled=cloud_enabled)
    provider = StaticProvider([json.dumps(plan)])
    router = ModelRouter(config, local=provider)
    return AgentRuntime(PolicyEngineService(), config=config, router=router)


def _request() -> AgentRequest:
    return AgentRequest(session_id="session-1", user_input="read the status")


def test_runtime_executes_validated_plan_through_policy_gateway() -> None:
    runtime = _runtime({
        "objective": "Read status",
        "steps": [{
            "step_id": "read",
            "tool_id": "fake_read_status",
            "operation": "read",
            "arguments": {"format": "json"},
        }],
    })

    result = runtime.submit(_request())

    assert result.status.value == "completed"
    assert result.completed_steps == ("read",)
    assert result.verification[0].passed is True
    assert runtime.status().completed == 1
    runtime.close()


def test_runtime_stops_at_confirmation_boundary() -> None:
    runtime = _runtime({
        "objective": "Modify data",
        "steps": [{
            "step_id": "modify",
            "tool_id": "fake_modify_user_data",
            "operation": "modify",
            "arguments": {"record_id": "r1", "value": "new"},
        }],
    })

    result = runtime.submit(_request())

    assert result.status.value == "awaiting_confirmation"
    assert result.failed_step == "modify"
    runtime.close()


def test_disable_preserves_normal_policy_boundary_and_rejects_agent_work() -> None:
    runtime = _runtime({
        "objective": "Read status",
        "steps": [{
            "step_id": "read",
            "tool_id": "fake_read_status",
            "operation": "read",
            "arguments": {"format": "json"},
        }],
    })

    runtime.disable()
    result = runtime.submit(_request())

    assert result.status.value == "disabled"
    assert runtime.status().control_state == "disabled"
    runtime.close()


def test_unknown_tool_plan_fails_closed_before_execution() -> None:
    runtime = _runtime({
        "objective": "Invent a capability",
        "steps": [{
            "step_id": "unknown",
            "tool_id": "not_registered",
            "operation": "run",
            "arguments": {},
        }],
    })

    result = runtime.submit(_request())

    assert result.status.value == "failed"
    assert result.degraded == ("plan_rejected",)
    assert runtime.status().plan_rejections == 1
    runtime.close()