"""Scope-bound typed capabilities using Phase 04's existing lease gateway."""

from pathlib import Path
from uuid import UUID

from pydantic import Field, field_serializer

from app.execution.models import ExecutionCode, ExecutionResult
from app.execution.policy import Phase04PolicyService
from app.policy.enums import AuthorizationLevel
from app.policy.registry import ToolDefinition

from .models import Candidate, MemoryType, Provenance, Query, Schema, Scope, SourceKind, Status, now
from .service import MemoryService


class StoreCandidateArgs(Schema):
    content: str = Field(min_length=1, max_length=8192)
    memory_type: MemoryType


class InspectArgs(Schema):
    memory_id: UUID

    @field_serializer("memory_id")
    def wire_id(self, value):
        return str(value)


class UpdateArgs(StoreCandidateArgs):
    memory_id: UUID
    expected_version: int = Field(ge=1, le=1000)

    @field_serializer("memory_id")
    def wire_id(self, value):
        return str(value)


class SearchArgs(Query):
    @field_serializer("since", "until")
    def wire_time(self, value):
        return value.isoformat() if value is not None else None


class MemoryPolicyService(Phase04PolicyService):
    """Trusted bootstrap binds scope. No namespace/approval/provenance in model args."""

    def __init__(self, memory: MemoryService, scope: Scope, workspace_root: Path | None = None):
        self._memory = memory
        self._scope = Scope.model_validate(scope.model_dump())
        super().__init__(workspace_root=workspace_root, event_bus=memory.bus)

    def _candidate(self, arguments: dict) -> Candidate:
        return Candidate(content=arguments["content"], memory_type=arguments["memory_type"],
                         provenance=Provenance(kind=SourceKind.DERIVED, source_id="model-candidate",
                                               source_timestamp=now(),
                                               conversation_id=self._scope.conversation_id))

    def _read(self, arguments: dict) -> dict:
        result = self._memory.retrieve(self._scope, Query.model_validate(arguments))
        return ExecutionResult(
            code=ExecutionCode.SUCCESS if result.available else ExecutionCode.EXECUTION_FAILED,
            message="memory retrieval completed" if result.available else "memory unavailable",
            data=result.model_dump(mode="json"),
        ).model_dump()

    def _inspect(self, arguments: dict) -> dict:
        result = self._memory.inspect(self._scope, UUID(str(arguments["memory_id"])))
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="memory inspected",
                               data={"record": result.model_dump(mode="json") if result else None}).model_dump()

    def _store_candidate(self, arguments: dict) -> dict:
        record = self._memory.capture(self._scope, self._candidate(arguments), approved=True)
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="candidate stored",
                               data={"memory_id": str(record.memory_id), "version": record.version}).model_dump()

    def _update(self, arguments: dict) -> dict:
        record = self._memory.correct(self._scope, UUID(str(arguments["memory_id"])),
                                      arguments["expected_version"], self._candidate(arguments), approved=True)
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="memory corrected",
                               data={"memory_id": str(record.memory_id), "version": record.version}).model_dump()

    def _delete(self, arguments: dict) -> dict:
        removed = self._memory.transition(self._scope, UUID(str(arguments["memory_id"])), Status.DELETED, approved=True)
        return ExecutionResult(code=ExecutionCode.SUCCESS, message="memory deletion processed",
                               data={"removed": removed}).model_dump()

    def _register_defaults(self) -> None:
        definitions = (
            ("retrieve_memory", SearchArgs, self._read, AuthorizationLevel.L0_READ_ONLY, False),
            ("inspect_memory", InspectArgs, self._inspect, AuthorizationLevel.L0_READ_ONLY, False),
            ("store_memory_candidate", StoreCandidateArgs, self._store_candidate, AuthorizationLevel.L2_USER_DATA_MODIFICATION, True),
            ("update_memory", UpdateArgs, self._update, AuthorizationLevel.L2_USER_DATA_MODIFICATION, True),
            ("delete_memory", InspectArgs, self._delete, AuthorizationLevel.L3_DESTRUCTIVE, True),
        )
        for name, schema, executor, level, confirmation in definitions:
            self.registry.register_tool(ToolDefinition(
                tool_id=name, name=name, description="Governed scope-bound memory data operation",
                authorization_level=level, requires_confirmation=confirmation,
                supported_operations=(name,), operation_models={name: schema},
                executor=self._executor({name: executor}), modify_user_data=confirmation,
            ))
        super()._register_defaults()