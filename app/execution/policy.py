"""Phase 04 typed capability registry integrated with the deterministic gateway."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.core.events import EventBus
from app.observability.events import EventType, StructuredEvent

from app.policy import AuthorizationLevel, DecisionState
from app.policy.models import AuditEvent, ToolRequest
from app.policy.registry import ToolDefinition
from app.policy.service import PolicyEngineService
from app.browser.config import BrowserConfig
from app.browser.executor import BrowserExecutor
from app.browser.provider import BrowserProvider
from app.browser.schemas import BrowserInspectArgs, BrowserNavigateArgs, BrowserScreenshotArgs, BrowserTargetArgs, BrowserTypeArgs

from .apps import ApplicationManager
from .filesystem import FilesystemExecutor
from .kali import KaliToolRegistry
from .models import ExecutionCode, ExecutionLimits, ExecutionResult
from .schemas import CloseAppArgs, CopyMoveArgs, CreateFileArgs, EmptyArgs, ForceCloseAppArgs, LaunchAppArgs, ListDirectoryArgs, ObserveAppArgs, PathArgs, ReadFileArgs, RefreshArgs, SearchFilesArgs, TerminalArgs, WriteFileArgs
from .terminal import TerminalExecutor


class Phase04PolicyService(PolicyEngineService):
    def __init__(self, workspace_root: Path | None = None, limits: ExecutionLimits | None = None, event_bus: EventBus | None = None, browser_config: BrowserConfig | None = None, browser_provider: BrowserProvider | None = None) -> None:
        self.limits = limits or ExecutionLimits()
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self._filesystem = FilesystemExecutor(self.workspace_root, self.limits)
        self._terminal = TerminalExecutor(self.workspace_root, self.limits)
        self._applications = ApplicationManager(self.limits.max_directory_entries)
        self._kali = KaliToolRegistry(max_tools=self.limits.max_directory_entries)
        self._execution_slots = threading.BoundedSemaphore(self.limits.max_concurrent_operations)
        self._operation_context = threading.local()
        self._browser = BrowserExecutor(browser_provider or BrowserProvider(browser_config))
        self.event_bus = event_bus or EventBus()
        super().__init__()

    def _register_defaults(self) -> None:
        definitions = [
              ("filesystem", AuthorizationLevel.L0_READ_ONLY, ("list_directory", "stat_path", "read_file", "search_files"), {"list_directory": ListDirectoryArgs, "stat_path": PathArgs, "read_file": ReadFileArgs, "search_files": SearchFilesArgs}, {"list_directory": self._filesystem.list_directory, "stat_path": self._filesystem.stat_path, "read_file": self._filesystem.read_file, "search_files": self._filesystem.search_files}, False),
              ("filesystem_write", AuthorizationLevel.L2_USER_DATA_MODIFICATION, ("create_file", "write_file", "copy_file", "move_file"), {"create_file": CreateFileArgs, "write_file": WriteFileArgs, "copy_file": CopyMoveArgs, "move_file": CopyMoveArgs}, {"create_file": lambda arguments: self._filesystem.write_file({**arguments, "overwrite": False}), "write_file": self._filesystem.write_file, "copy_file": self._filesystem.copy_file, "move_file": self._filesystem.move_file}, True),
              ("filesystem_delete", AuthorizationLevel.L3_DESTRUCTIVE, ("delete_file",), {"delete_file": PathArgs}, {"delete_file": self._filesystem.delete_file}, True),
              ("terminal", AuthorizationLevel.L0_READ_ONLY, ("execute",), {"execute": TerminalArgs}, {"execute": self._terminal.execute}, False),
              ("applications", AuthorizationLevel.L0_READ_ONLY, ("discover", "refresh"), {"discover": EmptyArgs, "refresh": RefreshArgs}, {"discover": lambda arguments: self._applications.discover(), "refresh": lambda arguments: self._applications.refresh()}, False),
              ("kali_capabilities", AuthorizationLevel.L0_READ_ONLY, ("discover", "refresh"), {"discover": EmptyArgs, "refresh": RefreshArgs}, {"discover": lambda arguments: self._kali.discover(), "refresh": lambda arguments: self._kali.discover(refresh=True)}, False),
            ("application_control", AuthorizationLevel.L1_REVERSIBLE, ("launch", "close", "observe"), {"launch": LaunchAppArgs, "close": CloseAppArgs, "observe": ObserveAppArgs}, {"launch": self._applications._launch, "close": self._applications._close, "observe": self._applications._observe}, True),
            ("application_terminate", AuthorizationLevel.L3_DESTRUCTIVE, ("force_close",), {"force_close": ForceCloseAppArgs}, {"force_close": self._applications._force_close}, True),
              ("browser_read", AuthorizationLevel.L0_READ_ONLY, ("navigate", "inspect", "screenshot"), {"navigate": BrowserNavigateArgs, "inspect": BrowserInspectArgs, "screenshot": BrowserScreenshotArgs}, {"navigate": lambda arguments: self._browser.read({**arguments, "operation": "navigate"}), "inspect": lambda arguments: self._browser.read({**arguments, "operation": "inspect"}), "screenshot": lambda arguments: self._browser.read({**arguments, "operation": "screenshot"})}, False),
              ("browser_action", AuthorizationLevel.L1_REVERSIBLE, ("click", "type"), {"click": BrowserTargetArgs, "type": BrowserTypeArgs}, {"click": lambda arguments: self._browser.action({**arguments, "operation": "click"}), "type": lambda arguments: self._browser.action({**arguments, "operation": "type"})}, True),
        ]
        for tool_id, level, operations, schemas, executors, confirmation in definitions:
            self.registry.register_tool(ToolDefinition(tool_id=tool_id, name=tool_id, description=f"Controlled {tool_id} capability", authorization_level=level, requires_confirmation=confirmation, supported_operations=operations, operation_models=schemas, resource_requirements={"timeout_seconds": self.limits.command_timeout_seconds}, executor=self._executor(executors)))
        self.registry.freeze()

    def _executor(self, executors: dict[str, Any]):
        def dispatch(arguments: dict[str, Any]) -> dict[str, Any]:
            operation = getattr(self._operation_context, "operation", None)
            if operation not in executors:
                return ExecutionResult(code=ExecutionCode.DENIED, message="operation is not registered").model_dump()
            return executors[operation](arguments)
        return dispatch

    def execute(self, request: ToolRequest) -> ExecutionResult:
        definition = self.registry.get_immutable_definition(request.tool_name)
        if definition is None or request.operation not in definition.operation_models:
            return ExecutionResult(code=ExecutionCode.DENIED, message="capability is not registered")
        decision, permit = self.process_request(request)
        if decision.decision is DecisionState.REQUIRE_CONFIRMATION:
            return ExecutionResult(code=ExecutionCode.CONFIRMATION_REQUIRED, message="explicit confirmation required")
        if decision.decision is not DecisionState.ALLOW or permit is None:
            return ExecutionResult(code=ExecutionCode.DENIED, message=decision.reason)
        if not self._execution_slots.acquire(blocking=False):
            return ExecutionResult(code=ExecutionCode.RESOURCE_LIMIT, message="concurrent execution limit reached")
        try:
            self._operation_context.operation = request.operation
            result = self.execute_with_permit(request, permit)
            typed_result = ExecutionResult.model_validate(result)
            self._audit_execution(request, typed_result)
            self.event_bus.publish(StructuredEvent(event_type=EventType.TOOL_COMPLETED if typed_result.success else EventType.TOOL_FAILED, component="execution", source="Phase04PolicyService.execute", request_id=request.request_id, tool_id=request.tool_name, operation=request.operation, success=typed_result.success, metadata={"code": typed_result.code.value}))
            return typed_result
        except Exception as error:
            return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED, message=type(error).__name__)
        finally:
            self._operation_context.operation = None
            self._execution_slots.release()

    def close(self) -> None:
        self._browser.provider.close()

    def _audit_execution(self, request: ToolRequest, result: ExecutionResult) -> None:
        self.audit_logger.record(AuditEvent(event_id=f"execution-{request.request_id}", request_id=request.request_id, tool_id=request.tool_name, requested_operation=request.operation, decision=DecisionState.ALLOW if result.success else DecisionState.POLICY_ERROR, authorization_level=None, confirmation_state="CONSUMED_OR_NOT_REQUIRED", resource_decision="ADMITTED", reason="execution completed" if result.success else "execution failed", source_subsystem="phase04.execution"))
