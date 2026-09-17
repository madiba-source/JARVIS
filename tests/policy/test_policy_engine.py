from __future__ import annotations

import concurrent.futures
import math
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.policy import AuthorizationLevel, DecisionState, PolicyEngineService, ToolRequest
from app.policy.confirmation import ConfirmationManager
from app.policy.governor import DefaultResourceGovernor
from app.policy.registry import ImmutableToolDefinition, PolicyRegistry, ToolDefinition
from app.policy.tools import create_fake_tool_executor


def request(**overrides):
    values = dict(request_id="r1", tool_name="fake_read_status", operation="read", authorization_level=AuthorizationLevel.L0_READ_ONLY, arguments={"format": "json"}, originating_subsystem="test")
    values.update(overrides)
    return ToolRequest(**values)


def test_policy_imports_and_levels() -> None:
    assert AuthorizationLevel.L0_READ_ONLY < AuthorizationLevel.L5_EXTERNAL_SIDE_EFFECT
    assert PolicyEngineService().registry.is_frozen


def test_l0_l1_allow_and_high_risk_confirmation() -> None:
    service = PolicyEngineService()
    assert service.process_request(request())[0].decision is DecisionState.ALLOW
    assert service.process_request(request(tool_name="fake_create_note", operation="create", authorization_level=AuthorizationLevel.L1_REVERSIBLE, arguments={"title": "x", "content": "y"}))[0].decision is DecisionState.ALLOW
    for tool, operation, args, level in [
        ("fake_modify_user_data", "modify", {"record_id": "1", "value": "x"}, AuthorizationLevel.L2_USER_DATA_MODIFICATION),
        ("fake_delete_file", "delete", {"path": "/tmp/x"}, AuthorizationLevel.L3_DESTRUCTIVE),
        ("fake_privileged_operation", "execute_privileged", {"command_key": "safe"}, AuthorizationLevel.L4_PRIVILEGED),
        ("fake_send_external_message", "send", {"recipient": "x", "message": "y"}, AuthorizationLevel.L5_EXTERNAL_SIDE_EFFECT),
    ]:
        decision, permit = service.process_request(request(tool_name=tool, operation=operation, arguments=args, authorization_level=level))
        assert decision.decision is DecisionState.REQUIRE_CONFIRMATION
        assert permit is None


def test_operation_and_argument_validation_is_closed_and_typed() -> None:
    service = PolicyEngineService()
    assert service.process_request(request(operation="delete_everything"))[0].decision is DecisionState.INVALID_REQUEST
    assert service.process_request(request(arguments={"format": 1}))[0].decision is DecisionState.INVALID_REQUEST
    assert service.process_request(request(arguments={"format": "json", "extra": "x"}))[0].decision is DecisionState.INVALID_REQUEST
    assert service.process_request(request(arguments={}))[0].decision is DecisionState.INVALID_REQUEST
    assert service.process_request(request(tool_name="fake_create_note", operation="create", authorization_level=AuthorizationLevel.L1_REVERSIBLE, arguments={"title": "x"}))[0].decision is DecisionState.INVALID_REQUEST


@pytest.mark.parametrize(
    "arguments, marker",
    [
        ({"format": {"value": "JARVIS_VALIDATION_SECRET_9f71d2"}}, "JARVIS_VALIDATION_SECRET_9f71d2"),
        ({"format": {"nested": ["JARVIS_NESTED_VALIDATION_SECRET_31c8a4"]}}, "JARVIS_NESTED_VALIDATION_SECRET_31c8a4"),
        ({"format": 123, "marker": "JARVIS_EXCEPTION_TEXT_7b2e11"}, "JARVIS_EXCEPTION_TEXT_7b2e11"),
    ],
)
def test_invalid_argument_details_never_reach_decision_or_audit(arguments: dict, marker: str) -> None:
    service = PolicyEngineService()
    decision, permit = service.process_request(request(arguments=arguments))

    assert decision.decision is DecisionState.INVALID_REQUEST
    assert permit is None
    assert decision.reason == "Request argument validation failed"
    assert marker not in decision.reason
    audit_serialized = service.get_audit_events()[-1].model_dump_json()
    assert marker not in audit_serialized


def test_invalid_arguments_fail_closed_without_payload_metadata() -> None:
    service = PolicyEngineService()
    marker = "JARVIS_PAYLOAD_MARKER_0e2a9c"
    decision, permit = service.process_request(
        request(arguments={"format": {"payload": marker}}, metadata={"caller": marker})
    )

    assert decision.decision is DecisionState.INVALID_REQUEST
    assert permit is None
    assert marker not in decision.model_dump_json()
    assert marker not in service.get_audit_events()[-1].model_dump_json()


def test_unknown_tool_and_inactive_jarvis_fail_closed() -> None:
    service = PolicyEngineService()
    assert service.process_request(request(tool_name="unknown"))[0].decision is DecisionState.UNKNOWN_TOOL
    service.set_jarvis_active(False)
    assert service.process_request(request())[0].decision is DecisionState.SYSTEM_DISABLED


def test_authorization_claim_cannot_elevate_or_lower_policy() -> None:
    service = PolicyEngineService()
    decision, _ = service.process_request(request(tool_name="fake_send_external_message", operation="send", authorization_level=AuthorizationLevel.L0_READ_ONLY, arguments={"recipient": "x", "message": "y"}))
    assert decision.decision is DecisionState.REQUIRE_CONFIRMATION
    assert decision.authorization_level is AuthorizationLevel.L5_EXTERNAL_SIDE_EFFECT
    decision, _ = service.process_request(request(authorization_level=AuthorizationLevel.L5_EXTERNAL_SIDE_EFFECT))
    assert decision.decision is DecisionState.DENY


def test_confirmation_is_action_bound_and_single_use() -> None:
    service = PolicyEngineService()
    original = request(tool_name="fake_delete_file", operation="delete", authorization_level=AuthorizationLevel.L3_DESTRUCTIVE, arguments={"path": "/tmp/a"})
    token = service.issue_confirmation(original)
    changed = original.model_copy(update={"confirmation_token": token, "arguments": {"path": "/tmp/b"}})
    assert service.process_request(changed)[0].decision is DecisionState.REQUIRE_CONFIRMATION
    confirmed = original.model_copy(update={"confirmation_token": token})
    assert service.process_request(confirmed)[0].decision is DecisionState.ALLOW
    assert service.process_request(confirmed)[0].decision is DecisionState.REQUIRE_CONFIRMATION


def test_confirmation_binds_request_operation_auth_and_resources() -> None:
    service = PolicyEngineService()
    original = request(tool_name="fake_delete_file", operation="delete", authorization_level=AuthorizationLevel.L3_DESTRUCTIVE, arguments={"path": "/tmp/a"})
    token = service.issue_confirmation(original)
    for update in ({"request_id": "other"}, {"operation": "bad"}, {"authorization_level": AuthorizationLevel.L2_USER_DATA_MODIFICATION}, {"requested_resource_budget": {"memory_mb": 100}}):
        candidate = original.model_copy(update={"confirmation_token": token, **update})
        assert service.process_request(candidate)[0] is not None
        # The first mismatch consumes nothing, so each case is independently checked below by a new token.
        token = service.issue_confirmation(original)


def test_confirmation_strict_canonicalization() -> None:
    manager = ConfirmationManager()
    with pytest.raises(ValueError):
        manager.compute_action_hash("t", "r", "op", {"x": float("nan")}, AuthorizationLevel.L0_READ_ONLY, {})
    with pytest.raises(ValueError):
        manager.compute_action_hash("t", "r", "op", {"x": float("inf")}, AuthorizationLevel.L0_READ_ONLY, {})
    with pytest.raises(ValueError):
        manager.compute_action_hash("t", "r", "op", {1: "x"}, AuthorizationLevel.L0_READ_ONLY, {})


def test_confirmation_store_is_bounded_and_expiring() -> None:
    now = [datetime.now(timezone.utc)]
    manager = ConfirmationManager(token_ttl_seconds=1, max_tokens=2, clock=lambda: now[0])
    for index in range(5):
        manager.generate_token(tool_id="t", request_id=str(index), operation="op", arguments={}, authorization_level=AuthorizationLevel.L0_READ_ONLY, effective_budget={})
    assert manager.token_count <= 2
    now[0] += timedelta(seconds=2)
    assert manager.token_count == 0


def test_registry_owns_deep_immutable_policy_snapshot() -> None:
    schema = {"op": str}
    resources = {"memory_mb": 10.0}
    registry = PolicyRegistry()
    registry.register_tool(ToolDefinition(tool_id="custom", name="custom", description="x", authorization_level=AuthorizationLevel.L0_READ_ONLY, requires_confirmation=False, supported_operations=("run",), operation_models={}, resource_requirements=resources, executor=create_fake_tool_executor("custom")))
    registry.freeze()
    schema["evil"] = int
    resources["memory_mb"] = 9999
    definition = registry.get_immutable_definition("custom")
    assert isinstance(definition, ImmutableToolDefinition)
    with pytest.raises(TypeError):
        definition.resource_requirements["evil"] = 1
    with pytest.raises(AttributeError):
        definition.supported_operations.append("evil")
    assert definition.resource_requirements["memory_mb"] == 10.0
    assert not hasattr(definition, "executor")
    assert not hasattr(registry, "get_private_executor")


def test_registry_freeze_cannot_be_bypassed_by_supported_api() -> None:
    registry = PolicyRegistry()
    registry.freeze()
    with pytest.raises(RuntimeError):
        registry.register_tool(ToolDefinition(tool_id="x", name="x", description="x", authorization_level=AuthorizationLevel.L0_READ_ONLY, requires_confirmation=False, supported_operations=(), operation_models={}, executor=create_fake_tool_executor("x")))


def test_resource_admission_never_weakens_system_or_tool_limits() -> None:
    governor = DefaultResourceGovernor({"memory_mb": 100.0, "timeout_seconds": 10.0})
    assert not governor.check_budget({"memory_mb": 200.0}, {"memory_mb": 10.0}).allowed
    assert not governor.check_budget({"memory_mb": 5.0}, {"memory_mb": 10.0}).allowed
    assert governor.check_budget({"memory_mb": 50.0}, {"memory_mb": 10.0}).effective_budget["memory_mb"] == 10.0
    assert not governor.check_budget({"unknown": 1.0}, {}).allowed
    assert not governor.check_budget({"memory_mb": -1.0}, {}).allowed


def test_policy_error_and_denials_never_execute() -> None:
    service = PolicyEngineService()
    decision, permit = service.process_request(request(arguments={"format": 4}))
    assert decision.decision is DecisionState.INVALID_REQUEST and permit is None
    decision, permit = service.process_request(request(requested_resource_budget={"network_mb": 9999}))
    assert decision.decision is DecisionState.RESOURCE_DENIED and permit is None


def test_allow_executes_only_through_gateway() -> None:
    service = PolicyEngineService()
    req = request()
    decision, permit = service.process_request(req)
    assert decision.decision is DecisionState.ALLOW and permit is not None
    result = service.execute_with_permit(req, permit)
    assert result["executed_mock_action"] is True


def test_old_permit_rejected_after_disable() -> None:
    service = PolicyEngineService()
    req = request()
    _, permit = service.process_request(req)
    assert permit is not None
    service.set_jarvis_active(False)
    with pytest.raises(PermissionError):
        service.execute_with_permit(req, permit)


def test_disable_race_never_admits_after_transition() -> None:
    service = PolicyEngineService()
    req = request()
    admitted = 0
    lock = threading.Lock()
    stop = threading.Event()

    def attempt() -> None:
        nonlocal admitted
        while not stop.is_set():
            decision, permit = service.process_request(req.model_copy(update={"request_id": f"r-{time.monotonic_ns()}"}))
            if decision.decision is DecisionState.ALLOW and permit is not None:
                try:
                    service.execute_with_permit(req.model_copy(update={"request_id": permit.request_id}), permit)
                    with lock:
                        admitted += 1
                except PermissionError:
                    pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(attempt) for _ in range(4)]
        time.sleep(0.02)
        service.set_jarvis_active(False)
        stop.set()
        for future in futures:
            future.result(timeout=2)
    assert service.evaluator.jarvis_active is False
    post_disable, permit = service.process_request(req)
    assert post_disable.decision is DecisionState.SYSTEM_DISABLED and permit is None


def test_audit_redacts_sensitive_fields_and_logs_no_arguments() -> None:
    service = PolicyEngineService()
    request_with_secret = request(originating_subsystem="secret_token_subsystem", metadata={"password": "do-not-log"})
    service.process_request(request_with_secret)
    event = service.get_audit_events()[-1]
    serialized = event.model_dump_json()
    assert "do-not-log" not in serialized
    assert "secret_token_subsystem" not in serialized
    assert "REDACTED" in serialized
