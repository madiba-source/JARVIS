"""Adversarial: permits minted outside the evaluator must never authorize execution."""

import pytest

from app.policy import AuthorizationLevel, DecisionState, PolicyEngineService, ToolRequest
from app.policy.confirmation import ConfirmationManager
from app.policy.evaluator import ExecutionPermit


def test_forged_permit_cannot_bypass_confirmation() -> None:
    service = PolicyEngineService()
    request = ToolRequest(
        request_id="forge-1",
        tool_name="fake_delete_file",
        operation="delete",
        authorization_level=AuthorizationLevel.L3_DESTRUCTIVE,
        arguments={"path": "/tmp/never-deleted"},
        originating_subsystem="test",
    )
    decision, permit = service.process_request(request)
    assert decision.decision is DecisionState.REQUIRE_CONFIRMATION
    assert permit is None

    # Mint a permit shaped exactly like a real one using only public information.
    forged = ExecutionPermit(
        permit_id="permit_forged",
        request_id=request.request_id,
        tool_id="fake_delete_file",
        operation="delete",
        action_hash=ConfirmationManager.compute_action_hash(
            "fake_delete_file",
            request.request_id,
            "delete",
            {"path": "/tmp/never-deleted"},
            AuthorizationLevel.L3_DESTRUCTIVE,
            {},
        ),
        generation=service.evaluator.active_generation,
        effective_budget={},
    )
    with pytest.raises(PermissionError):
        service.execute_with_permit(request, forged)