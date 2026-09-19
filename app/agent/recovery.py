"""Bounded recovery decisions.

Recovery never invents capability that does not exist. Phase 04 exposes no
rollback, so `ROLLBACK_IF_SUPPORTED` is never selected today; it exists so a
future capability can be wired in without changing the decision surface.

Two rules dominate:

* a step that may already have produced an external side effect is never
  retried speculatively — it is verified, then escalated;
* an uncertain outcome is never reported as recovered.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .config import AgentConfig
from .execution import StepExecution
from .models import (
    Escalation, ObservationCode, RecoveryStrategy, Schema, StepStatus, safe_summary,
)
from .plan_validation import ValidatedStep

UNCERTAIN_CODES = frozenset({
    ObservationCode.TIMEOUT.value,
    ObservationCode.EXECUTION_FAILED.value,
    ObservationCode.UNAVAILABLE.value,
})
POLICY_CODES = frozenset({
    ObservationCode.DENIED.value,
    ObservationCode.INVALID_REQUEST.value,
    ObservationCode.DISABLED.value,
})
ACTIONS = {
    RecoveryStrategy.ESCALATE_TO_USER: "Approve, adjust the request, or take over manually.",
    RecoveryStrategy.STOP: "Change the request or enable the required capability.",
    RecoveryStrategy.ALTERNATIVE_STEP: "No action needed yet; the runtime will replan once.",
}


class RecoveryDecision(Schema):
    strategy: RecoveryStrategy
    reason_code: str = Field(default="", max_length=64)
    escalation: Escalation | None = None


class RecoveryEngine:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config

    def decide(self, step: ValidatedStep, execution: StepExecution, *, request_id: str,
               remaining: tuple[str, ...], replans_used: int) -> RecoveryDecision:
        observation = execution.observation
        code = observation.code
        if execution.status is StepStatus.SUCCEEDED:
            return RecoveryDecision(strategy=RecoveryStrategy.STOP, reason_code="completed")
        if execution.status is StepStatus.CANCELLED:
            return RecoveryDecision(strategy=RecoveryStrategy.STOP, reason_code="cancelled")
        if code == ObservationCode.CONFIRMATION_REQUIRED.value:
            return self._escalate(request_id, step, execution, remaining, "awaiting confirmation",
                                  "Human confirmation is required before this step can run.")
        if code == ObservationCode.LOOP_DETECTED.value:
            return self._escalate(request_id, step, execution, remaining, "loop detected",
                                  "Rephrase the request; the same action kept failing.")
        if code in POLICY_CODES:
            return self._escalate(request_id, step, execution, remaining, "policy refused the step",
                                  "The step was refused by policy; adjust the request.")
        if code == ObservationCode.BUDGET_EXCEEDED.value:
            return RecoveryDecision(strategy=RecoveryStrategy.STOP, reason_code="budget_exceeded")
        if step.side_effecting and code in UNCERTAIN_CODES:
            return self._escalate(request_id, step, execution, remaining,
                                  "uncertain outcome on a side-effecting step",
                                  "Verify the real system state before continuing.")
        if replans_used >= self._config.max_replans:
            return RecoveryDecision(strategy=RecoveryStrategy.STOP, reason_code="replan_budget_exhausted")
        return RecoveryDecision(strategy=RecoveryStrategy.ALTERNATIVE_STEP, reason_code="replan_available")

    @staticmethod
    def _escalate(request_id: str, step: ValidatedStep, execution: StepExecution,
                  remaining: tuple[str, ...], reason: str, action: str) -> RecoveryDecision:
        strategy = RecoveryStrategy.ESCALATE_TO_USER
        escalation = Escalation(
            request_id=request_id,
            step_id=step.step_id,
            attempted=safe_summary(f"{step.tool_id}.{step.operation}", 256),
            happened=safe_summary(execution.observation.summary or execution.observation.code, 256),
            remaining=tuple(remaining[:16]),
            stopped_because=safe_summary(reason, 128),
            required_user_action=ACTIONS.get(strategy, ""),
        )
        return RecoveryDecision(strategy=strategy, reason_code=reason.split()[0][:32],
                                escalation=escalation)

    def describe(self) -> dict[str, Any]:
        return {"max_replans": self._config.max_replans,
                "rollback_available": False,
                "strategies": [item.value for item in RecoveryStrategy]}
