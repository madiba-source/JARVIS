"""Bounded agent error taxonomy.

Every error carries a fixed machine code. Codes are the only part of an error
that telemetry may record: messages, argument values and exception text are not
copied into events, metrics or audit records.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for agent runtime failures with a stable machine code."""

    code = "agent_error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class AgentConfigurationError(AgentError):
    code = "configuration_invalid"


class GatewayUnavailable(AgentError):
    code = "gateway_unavailable"


class DisabledError(AgentError):
    code = "jarvis_disabled"


class AgentCancelled(AgentError):
    code = "cancelled"


class BudgetExceeded(AgentError):
    code = "budget_exceeded"


class RuntimeDeadlineExceeded(BudgetExceeded):
    code = "runtime_deadline_exceeded"


class PlanRejected(AgentError):
    code = "plan_rejected"


class PlanValidationError(PlanRejected):
    code = "plan_invalid"


class UnknownTool(PlanRejected):
    code = "unknown_tool"


class UnknownOperation(PlanRejected):
    code = "unknown_operation"


class ArgumentRejected(PlanRejected):
    code = "argument_rejected"


class ModelUnavailable(AgentError):
    code = "model_unavailable"


class ModelOutputInvalid(PlanRejected):
    code = "model_output_invalid"


class ConfirmationUnavailable(AgentError):
    code = "confirmation_unavailable"


class ConfirmationRejected(AgentError):
    code = "confirmation_rejected"


class VerificationFailed(AgentError):
    code = "verification_failed"


class LoopDetected(AgentError):
    code = "loop_detected"


class QueueFull(AgentError):
    code = "queue_full"


class QueueClosed(AgentError):
    code = "queue_closed"


class SessionLimitReached(AgentError):
    code = "session_limit_reached"


class DuplicateExecution(AgentError):
    code = "duplicate_execution"


class IdempotencyConflict(AgentError):
    code = "idempotency_conflict"


class UnavailableCapability(AgentError):
    code = "capability_unavailable"


class ShuttingDown(AgentError):
    code = "shutting_down"
