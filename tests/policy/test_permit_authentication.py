"""Defensive contract tests for evaluator-issued execution permits."""

import pytest

from app.policy import AuthorizationLevel, DecisionState, PolicyEngineService, ToolRequest
from app.policy.evaluator import ExecutionPermit


def read_request() -> ToolRequest:
    return ToolRequest(
        request_id="authenticated-read",
        tool_name="fake_read_status",
        operation="read",
        authorization_level=AuthorizationLevel.L0_READ_ONLY,
        arguments={"format": "json"},
        originating_subsystem="test",
    )


def test_issued_permit_survives_json_round_trip() -> None:
    service = PolicyEngineService()
    request = read_request()
    decision, permit = service.process_request(request)
    assert decision.decision is DecisionState.ALLOW
    assert permit is not None
    assert len(permit.signature) == 64
    restored = ExecutionPermit.model_validate_json(permit.model_dump_json())
    result = service.execute_with_permit(request, restored)
    assert result["executed_mock_action"] is True


def test_confirmed_action_receives_usable_authenticated_permit() -> None:
    service = PolicyEngineService()
    request = ToolRequest(
        request_id="authenticated-note-update",
        tool_name="fake_modify_user_data",
        operation="modify",
        authorization_level=AuthorizationLevel.L2_USER_DATA_MODIFICATION,
        arguments={"record_id": "test-record", "value": "test-value"},
        originating_subsystem="test",
    )
    decision, permit = service.process_request(request)
    assert decision.decision is DecisionState.REQUIRE_CONFIRMATION
    assert permit is None
    token = service.issue_confirmation(request)
    confirmed = request.model_copy(update={"confirmation_token": token})
    decision, permit = service.process_request(confirmed)
    assert decision.decision is DecisionState.ALLOW
    assert permit is not None
    assert service.execute_with_permit(confirmed, permit)["executed_mock_action"] is True


def test_issued_permit_is_not_transferable_between_evaluators() -> None:
    issuer = PolicyEngineService()
    other = PolicyEngineService()
    request = read_request()
    _, permit = issuer.process_request(request)
    assert permit is not None
    with pytest.raises(PermissionError, match="authentication failed"):
        other.execute_with_permit(request, permit)
    assert issuer.execute_with_permit(request, permit)["executed_mock_action"] is True


def test_reenable_does_not_restore_old_permits() -> None:
    service = PolicyEngineService()
    request = read_request()
    _, old_permit = service.process_request(request)
    assert old_permit is not None
    service.set_jarvis_active(False)
    service.set_jarvis_active(True)
    with pytest.raises(PermissionError, match="invalidated"):
        service.execute_with_permit(request, old_permit)
    _, new_permit = service.process_request(request)
    assert new_permit is not None
    assert service.execute_with_permit(request, new_permit)["executed_mock_action"] is True