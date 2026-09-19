"""Agent-facing adapter over the Phase 03/04 policy gateway.

The adapter exists for two reasons and no others:

1. Phase 04's service exposes `execute`, while the Phase 03 simulation service
   exposes `process_request` + `execute_with_permit`. The adapter gives the
   runtime one uniform, policy-mediated entry point for both.
2. The runtime must be able to hold a read-only catalog without holding the
   registry itself.

Every call still crosses the deterministic evaluator, the resource governor, the
confirmation manager and the execution lease. The adapter adds no authority, no
cache and no bypass. It deliberately exposes no executor handle.
"""

from __future__ import annotations

import threading
from typing import Any

from app.policy.models import AuditEvent, PolicyDecision, ToolRequest

from .catalog import ToolCatalog
from .errors import ConfirmationUnavailable
from .ports import decision_is_allow, decision_requires_confirmation, denied_code, normalize_tool_result
from app.execution.models import ExecutionCode, ExecutionResult

MAX_FALLBACK_CONCURRENCY = 4


class ExecutionGateway:
    """Uniform policy-mediated execution for the agent runtime."""

    def __init__(self, service: Any, max_concurrency: int = MAX_FALLBACK_CONCURRENCY) -> None:
        if not hasattr(service, "process_request") or not hasattr(service, "registry"):
            raise TypeError("a policy service with a registry is required")
        self._service = service
        self.catalog = ToolCatalog(service.registry)
        self._slots = threading.BoundedSemaphore(max(1, min(int(max_concurrency), MAX_FALLBACK_CONCURRENCY)))
        self._lock = threading.RLock()
        self._closed = False

    @property
    def available(self) -> bool:
        with self._lock:
            return not self._closed

    def close(self) -> None:
        with self._lock:
            self._closed = True

    # --- policy ---------------------------------------------------------
    def evaluate(self, request: ToolRequest) -> PolicyDecision | None:
        """Evaluate without executing. Performs no tool invocation."""
        try:
            decision, _permit = self._service.process_request(request)
        except Exception:
            return None
        return decision

    def issue_confirmation(self, request: ToolRequest) -> str:
        try:
            return str(self._service.issue_confirmation(request))
        except Exception:
            raise ConfirmationUnavailable("confirmation cannot be issued") from None

    def set_active(self, active: bool) -> None:
        try:
            self._service.set_jarvis_active(bool(active))
        except Exception:
            return

    def record_audit(self, event: AuditEvent) -> bool:
        """Delegate to the existing audit mechanism. Never raises."""
        logger = getattr(self._service, "audit_logger", None)
        try:
            logger.record(event)
            return True
        except Exception:
            return False

    def audit_events(self) -> tuple[AuditEvent, ...]:
        getter = getattr(self._service, "get_audit_events", None)
        try:
            return tuple(getter()) if callable(getter) else ()
        except Exception:
            return ()

    # --- execution ------------------------------------------------------
    def execute(self, request: ToolRequest) -> ExecutionResult:
        """Execute one typed request through the authoritative policy path."""
        with self._lock:
            if self._closed:
                return ExecutionResult(code=ExecutionCode.UNAVAILABLE, message="gateway is closed")
        try:
            native = getattr(self._service, "execute", None)
            if callable(native):
                return normalize_tool_result(native(request))
            return self._execute_via_policy(request)
        except Exception as error:
            # Exception text, arguments and paths never reach the result.
            return ExecutionResult(code=ExecutionCode.EXECUTION_FAILED,
                                   message=type(error).__name__[:64] or "execution failed")

    def _execute_via_policy(self, request: ToolRequest) -> ExecutionResult:
        decision, permit = self._service.process_request(request)
        if decision_requires_confirmation(decision):
            return ExecutionResult(code=ExecutionCode.CONFIRMATION_REQUIRED,
                                   message="explicit confirmation required")
        if not decision_is_allow(decision) or permit is None:
            return ExecutionResult(code=denied_code(decision), message="policy denied")
        if not self._slots.acquire(blocking=False):
            return ExecutionResult(code=ExecutionCode.RESOURCE_LIMIT,
                                   message="concurrent execution limit reached")
        try:
            return normalize_tool_result(self._service.execute_with_permit(request, permit))
        finally:
            self._slots.release()

    # --- status ---------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {"available": self.available, "tools": len(self.catalog.tool_ids)}
