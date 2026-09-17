"""Deterministic admission evaluator and atomic execution lease manager."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .audit import AuditLogger
from .confirmation import ConfirmationManager
from .enums import AuthorizationLevel, DecisionState
from .governor import DefaultResourceGovernor
from .models import AuditEvent, PolicyDecision, ToolRequest
from .registry import PolicyRegistry
from .snapshot import OwnedArgumentsSnapshot


class ExecutionPermit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    permit_id: str
    request_id: str
    tool_id: str
    operation: str
    action_hash: str
    generation: int
    effective_budget: dict[str, float] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature: str = Field(default="", repr=False)
    argument_snapshot: str = Field(default="", repr=False)


class ExecutionLease(AbstractContextManager["ExecutionLease"]):
    def __init__(self, evaluator: "PolicyEvaluator", permit: ExecutionPermit) -> None:
        self._evaluator = evaluator
        self.permit = permit
        self._snapshot = OwnedArgumentsSnapshot(permit.argument_snapshot)
        self._released = False

    def execution_arguments(self) -> dict[str, Any]:
        """Produce an executor-owned payload from the authenticated snapshot."""
        if self._released:
            raise PermissionError("execution lease has been released")
        return self._snapshot.materialize()

    def __enter__(self) -> "ExecutionLease":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if not self._released:
            self._evaluator._release_lease()
            self._released = True


class PolicyEvaluator:
    def __init__(self, registry: PolicyRegistry, confirmations: ConfirmationManager, governor: DefaultResourceGovernor, audit: AuditLogger) -> None:
        self.registry = registry
        self.confirmations = confirmations
        self.governor = governor
        self.audit = audit
        self._active = True
        self._generation = 0
        self._lock = threading.RLock()
        self._in_flight = 0
        self._permit_key = secrets.token_bytes(32)

    def _sign_permit(self, permit: ExecutionPermit) -> str:
        """Authenticate every permit field except the signature itself."""
        payload = json.dumps(
            permit.model_dump(mode="json", exclude={"signature"}),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hmac.new(self._permit_key, payload, hashlib.sha256).hexdigest()

    @property
    def jarvis_active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def active_generation(self) -> int:
        with self._lock:
            return self._generation

    def set_jarvis_active(self, active: bool) -> None:
        with self._lock:
            self._active = active
            self._generation += 1

    def acquire_execution_lease(self, permit: ExecutionPermit, request: ToolRequest) -> ExecutionLease:
        with self._lock:
            try:
                if not isinstance(permit, ExecutionPermit):
                    raise ValueError("invalid permit type")
                # Verify and use the same owned permit, including its nested budget.
                permit = permit.model_copy(deep=True)
                authentic = hmac.compare_digest(
                    permit.signature, self._sign_permit(permit)
                )
            except (TypeError, ValueError):
                authentic = False
            if not authentic:
                raise PermissionError("execution permit authentication failed")
            if not self._active or permit.generation != self._generation:
                raise PermissionError("execution permit invalidated by JARVIS state")
            if (permit.request_id, permit.tool_id, permit.operation) != (request.request_id, request.tool_name, request.operation):
                raise PermissionError("execution permit content mismatch")
            definition = self.registry.get_immutable_definition(permit.tool_id)
            if definition is None:
                raise PermissionError("registered tool no longer exists")
            if permit.operation not in definition.operation_models:
                raise PermissionError("operation is no longer registered")
            try:
                normalized_arguments = OwnedArgumentsSnapshot(permit.argument_snapshot).materialize()
            except (TypeError, ValueError, RecursionError) as error:
                raise PermissionError("invalid authorized argument snapshot") from error
            expected = ConfirmationManager.compute_action_hash(definition.tool_id, permit.request_id, permit.operation, normalized_arguments, definition.authorization_level, permit.effective_budget)
            if expected != permit.action_hash:
                raise PermissionError("execution permit action hash mismatch")
            self._in_flight += 1
            return ExecutionLease(self, permit)

    def _release_lease(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def _decision(self, request: ToolRequest, state: DecisionState, level: AuthorizationLevel | None, confirmation: bool, reason: str) -> PolicyDecision:
        decision = PolicyDecision(request_id=request.request_id, decision=state, tool_name=request.tool_name, authorization_level=level, requires_confirmation=confirmation, reason=reason)
        self.audit.record(AuditEvent(event_id=f"audit_{uuid.uuid4().hex}", request_id=request.request_id, tool_id=request.tool_name, requested_operation=request.operation, decision=state, authorization_level=level, confirmation_state="NOT_USED", resource_decision="NOT_USED", reason=reason, source_subsystem=request.originating_subsystem))
        return decision

    def evaluate(self, request: ToolRequest) -> tuple[PolicyDecision, ExecutionPermit | None]:
        try:
            definition = self.registry.get_immutable_definition(request.tool_name)
            if definition is None:
                return self._decision(request, DecisionState.UNKNOWN_TOOL, None, False, "tool is not registered"), None
            if not self.jarvis_active:
                return self._decision(request, DecisionState.SYSTEM_DISABLED, definition.authorization_level, definition.requires_confirmation, "JARVIS is disabled"), None
            if request.operation not in definition.supported_operations or request.operation not in definition.operation_models:
                return self._decision(request, DecisionState.INVALID_REQUEST, definition.authorization_level, definition.requires_confirmation, "operation is not supported"), None
            try:
                owned_input = deepcopy(request.arguments)
                validated = definition.operation_models[request.operation].model_validate(owned_input)
                snapshot = OwnedArgumentsSnapshot.capture(validated.model_dump(mode="python"))
                normalized_arguments = snapshot.materialize()
            except Exception as error:
                return self._decision(request, DecisionState.INVALID_REQUEST, definition.authorization_level, definition.requires_confirmation, f"argument validation failed: {error}"), None
            resource = self.governor.check_budget(request.requested_resource_budget, definition.resource_requirements)
            if not resource.allowed:
                return self._decision(request, DecisionState.RESOURCE_DENIED, definition.authorization_level, definition.requires_confirmation, resource.reason), None
            if request.authorization_level > definition.authorization_level:
                return self._decision(request, DecisionState.DENY, definition.authorization_level, definition.requires_confirmation, "authorization claim exceeds registered policy"), None
            with self._lock:
                if not self._active:
                    return self._decision(request, DecisionState.SYSTEM_DISABLED, definition.authorization_level, definition.requires_confirmation, "JARVIS disabled during evaluation"), None
                generation = self._generation
            effective = resource.effective_budget
            if definition.requires_confirmation and not self.confirmations.validate_and_consume(request.confirmation_token, tool_id=definition.tool_id, request_id=request.request_id, operation=request.operation, arguments=normalized_arguments, authorization_level=definition.authorization_level, effective_budget=effective):
                return self._decision(request, DecisionState.REQUIRE_CONFIRMATION, definition.authorization_level, True, "explicit user confirmation required"), None
            action_hash = ConfirmationManager.compute_action_hash(definition.tool_id, request.request_id, request.operation, normalized_arguments, definition.authorization_level, effective)
            permit = ExecutionPermit(permit_id=f"permit_{uuid.uuid4().hex}", request_id=request.request_id, tool_id=definition.tool_id, operation=request.operation, action_hash=action_hash, generation=generation, effective_budget=effective, argument_snapshot=snapshot.payload)
            permit = permit.model_copy(update={"signature": self._sign_permit(permit)})
            return self._decision(request, DecisionState.ALLOW, definition.authorization_level, definition.requires_confirmation, "policy admission accepted"), permit
        except Exception as error:
            return self._decision(request, DecisionState.POLICY_ERROR, None, True, f"policy evaluation failed: {type(error).__name__}"), None
