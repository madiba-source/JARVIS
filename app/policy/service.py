"""Public policy service and the only supported execution gateway."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr

from .audit import AuditLogger
from .confirmation import ConfirmationManager
from .enums import AuthorizationLevel, DecisionState
from .evaluator import ExecutionPermit, PolicyEvaluator
from .governor import DefaultResourceGovernor
from .models import AuditEvent, PolicyDecision, ToolRequest
from .registry import PolicyRegistry, ToolDefinition
from .tools import create_fake_tool_executor


class _ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: StrictStr


class _CreateNoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr
    content: StrictStr


class _ModifyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: StrictStr
    value: StrictStr


class _DeleteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: StrictStr


class _PrivilegedArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_key: StrictStr


class _MessageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient: StrictStr
    message: StrictStr


class PolicyEngineService:
    def __init__(self, resource_governor: DefaultResourceGovernor | None = None) -> None:
        self.registry = PolicyRegistry()
        self.confirmation_manager = ConfirmationManager()
        self.audit_logger = AuditLogger()
        self.governor = resource_governor or DefaultResourceGovernor()
        self.evaluator = PolicyEvaluator(self.registry, self.confirmation_manager, self.governor, self.audit_logger)
        self._register_defaults()

    def _register_defaults(self) -> None:
        definitions = [
            ("fake_read_status", AuthorizationLevel.L0_READ_ONLY, False, ("read", "status"), {"read": _ReadArgs, "status": _ReadArgs}, {"memory_mb": 50.0}),
            ("fake_create_note", AuthorizationLevel.L1_REVERSIBLE, False, ("create",), {"create": _CreateNoteArgs}, {}),
            ("fake_modify_user_data", AuthorizationLevel.L2_USER_DATA_MODIFICATION, True, ("modify", "update"), {"modify": _ModifyArgs, "update": _ModifyArgs}, {}),
            ("fake_delete_file", AuthorizationLevel.L3_DESTRUCTIVE, True, ("delete",), {"delete": _DeleteArgs}, {}),
            ("fake_privileged_operation", AuthorizationLevel.L4_PRIVILEGED, True, ("execute_privileged",), {"execute_privileged": _PrivilegedArgs}, {}),
            ("fake_send_external_message", AuthorizationLevel.L5_EXTERNAL_SIDE_EFFECT, True, ("send",), {"send": _MessageArgs}, {}),
        ]
        for tool_id, level, confirmation, operations, schemas, requirements in definitions:
            self.registry.register_tool(ToolDefinition(tool_id=tool_id, name=tool_id, description=f"Safe fake {tool_id}", authorization_level=level, requires_confirmation=confirmation, supported_operations=operations, operation_models=schemas, resource_requirements=requirements, executor=create_fake_tool_executor(tool_id)))
        self.registry.freeze()

    def process_request(self, request: ToolRequest) -> tuple[PolicyDecision, ExecutionPermit | None]:
        return self.evaluator.evaluate(request)

    def issue_confirmation(self, request: ToolRequest) -> str:
        pending, permit = self.process_request(request.model_copy(update={"confirmation_token": None}))
        if pending.decision is not DecisionState.REQUIRE_CONFIRMATION or permit is not None:
            raise ValueError("confirmation can only be issued for a valid pending policy decision")
        definition = self.registry.get_immutable_definition(request.tool_name)
        if definition is None:
            raise ValueError("unknown tool")
        resource = self.governor.check_budget(request.requested_resource_budget, definition.resource_requirements)
        if not resource.allowed:
            raise ValueError("resource admission denied")
        arguments = definition.operation_models[request.operation].model_validate(request.arguments).model_dump(mode="python")
        return self.confirmation_manager.generate_token(tool_id=definition.tool_id, request_id=request.request_id, operation=request.operation, arguments=arguments, authorization_level=definition.authorization_level, effective_budget=resource.effective_budget)

    def execute_with_permit(self, request: ToolRequest, permit: ExecutionPermit) -> dict[str, Any]:
        with self.evaluator.acquire_execution_lease(permit, request):
            definition = self.registry.get_immutable_definition(request.tool_name)
            if definition is None:
                raise PermissionError("registered tool no longer exists")
            operation_model = definition.operation_models.get(request.operation)
            if operation_model is None:
                raise PermissionError("operation is no longer registered")
            arguments = operation_model.model_validate(request.arguments).model_dump(mode="python")
            return self.registry._invoke_for_gateway(request.tool_name, arguments)

    def set_jarvis_active(self, active: bool) -> None:
        self.evaluator.set_jarvis_active(active)

    def get_audit_events(self) -> list[AuditEvent]:
        return self.audit_logger.get_events()
