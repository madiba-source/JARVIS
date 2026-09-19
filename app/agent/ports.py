"""Structural interfaces the agent runtime depends on.

These Protocols describe what the runtime needs. They deliberately require a
Phase 03/04 style policy service: an object that can evaluate a typed request,
execute an admitted request, and report its own active state. Nothing here lets
the runtime execute a tool directly, and nothing here grants authority.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from app.execution.models import ExecutionCode, ExecutionResult
from app.policy.enums import DecisionState
from app.policy.models import PolicyDecision, ToolRequest

_MALFORMED = "malformed tool result"


@runtime_checkable
class PolicyGateway(Protocol):
    """The only supported execution path for agent steps."""

    def process_request(self, request: ToolRequest) -> tuple[PolicyDecision, Any]:
        """Evaluate a request without executing it."""

    def issue_confirmation(self, request: ToolRequest) -> str:
        """Mint a single-use, action-bound confirmation token."""

    def execute_with_permit(self, request: ToolRequest, permit: Any) -> Any:
        """Execute an already-admitted request under an execution lease."""

    def set_jarvis_active(self, active: bool) -> None:
        """Update the authoritative active state."""

    @property
    def registry(self) -> Any:
        """The trusted tool registry. Read-only use only."""


@runtime_checkable
class StructuredPlanSource(Protocol):
    """A model that can return bounded structured text."""

    def complete(self, prompt: str, *, max_output_tokens: int, timeout: float,
                 cancel: Any = None) -> Any:
        """Return a typed model response; never raise transport errors."""


def decision_requires_confirmation(decision: PolicyDecision | None) -> bool:
    return decision is not None and decision.decision is DecisionState.REQUIRE_CONFIRMATION


def decision_is_allow(decision: PolicyDecision | None) -> bool:
    return decision is not None and decision.decision is DecisionState.ALLOW


_DENIED_CODES = {
    DecisionState.SYSTEM_DISABLED: ExecutionCode.DENIED,
    DecisionState.UNKNOWN_TOOL: ExecutionCode.INVALID_REQUEST,
    DecisionState.INVALID_REQUEST: ExecutionCode.INVALID_REQUEST,
    DecisionState.RESOURCE_DENIED: ExecutionCode.RESOURCE_LIMIT,
    DecisionState.POLICY_ERROR: ExecutionCode.EXECUTION_FAILED,
    DecisionState.DENY: ExecutionCode.DENIED,
    DecisionState.REQUIRE_CONFIRMATION: ExecutionCode.CONFIRMATION_REQUIRED,
}


def denied_code(decision: PolicyDecision | None) -> ExecutionCode:
    if decision is None:
        return ExecutionCode.DENIED
    return _DENIED_CODES.get(decision.decision, ExecutionCode.DENIED)


def bounded_mapping(value: dict) -> dict:
    """Canonicalize tool output through the owned-argument bounds."""
    from .models import owned_arguments

    try:
        parsed = json.loads(owned_arguments(value))
    except (ValueError, TypeError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_tool_result(value: object) -> ExecutionResult:
    """Normalize a tool return value into one typed result.

    Phase 04 returns `ExecutionResult`. The Phase 03 simulation service returns
    the fake executor's own mapping. Both are reduced here so the runtime never
    has to guess what a tool returned.
    """
    if isinstance(value, ExecutionResult):
        return value
    if not isinstance(value, dict):
        return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message="unsupported tool result")
    if "code" in value:
        try:
            return ExecutionResult.model_validate(value)
        except (ValueError, TypeError):
            return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=_MALFORMED)
    if value.get("status") == "success":
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="simulated tool completed",
                               data=bounded_mapping(value))
    return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message="simulated tool failed")
