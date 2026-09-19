"""Execute one validated step through the policy checkpoint.

For every attempt, in this order:

    control gate -> cancellation -> budget -> idempotency claim
    -> typed request -> policy evaluate/execute -> confirmation if required
    -> observation -> audit -> loop accounting

The executor has no authority of its own. It cannot invoke a tool, cannot skip
confirmation, cannot widen an argument set, and cannot resume a plan that a
disable has invalidated. It holds no permit between attempts: each attempt is
its own policy evaluation, so authorization is never reused.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.execution.models import ExecutionCode, ExecutionResult
from app.policy.models import ToolRequest

from .cancel import CancellationToken
from .confirmation import ConfirmationProvider, DenyConfirmationProvider
from .control import AgentControl
from .errors import AgentCancelled, DisabledError
from .events import AgentEventType
from .gateway import ExecutionGateway
from .idempotency import IdempotencyRegistry
from .loop import LoopDetector
from .models import (
    Observation, ObservationCode, PendingConfirmation, StepStatus, build_observation,
)
from .observation import observation_from_result
from .plan_validation import ValidatedPlan, ValidatedStep
from .telemetry import AgentTelemetry


@dataclass(frozen=True)
class StepExecution:
    """Internal transport between the executor and the coordinator."""

    step_id: str
    status: StepStatus
    observation: Observation
    attempts: int = 1
    reason_code: str = ""
    pending: PendingConfirmation | None = None
    cancellation_pending: bool = False
    exhausted: bool = False


class StepExecutor:
    def __init__(self, config: Any, gateway: ExecutionGateway, telemetry: AgentTelemetry,
                 control: AgentControl, registry: IdempotencyRegistry,
                 loops: LoopDetector) -> None:
        self._config = config
        self._gateway = gateway
        self._telemetry = telemetry
        self._control = control
        self._registry = registry
        self._loops = loops

    def execute(self, plan: ValidatedPlan, step: ValidatedStep, *, request_id: str,
                generation: int, budget: Any, cancel: CancellationToken,
                confirmations: ConfirmationProvider | None = None,
                allow_reentry: bool = False) -> StepExecution:
        key = IdempotencyRegistry.key(request_id, plan.plan_id, step.step_id, plan.version)
        recorded = self._registry.recorded(key)
        if recorded is not None and not allow_reentry:
            return StepExecution(step_id=step.step_id, status=_status_for(recorded),
                                 observation=recorded, attempts=0, reason_code="deduplicated")
        if not self._registry.claim(key, allow_reentry=allow_reentry) and not allow_reentry:
            return StepExecution(step_id=step.step_id, status=StepStatus.FAILED,
                                 observation=build_observation(step.step_id,
                                                               ObservationCode.DUPLICATE,
                                                               "duplicate step execution"),
                                 reason_code="duplicate_execution")
        try:
            result = self._run_attempts(plan, step, request_id, generation, budget, cancel,
                                        confirmations or DenyConfirmationProvider())
        finally:
            self._registry.release(key)
        if result.status in (StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.CANCELLED):
            self._registry.record(key, result.observation)
        return result

    # --- attempt loop ---------------------------------------------------
    def _run_attempts(self, plan: ValidatedPlan, step: ValidatedStep, request_id: str,
                      generation: int, budget: Any, cancel: CancellationToken,
                      confirmations: ConfirmationProvider) -> StepExecution:
        maximum = max(1, min(step.retry_policy.max_attempts, self._config.max_retries + 1))
        attempt = 0
        last: StepExecution | None = None
        while attempt < maximum:
            attempt += 1
            self._control.wait_until_runnable(cancel, budget.deadline)
            self._control.require_current(generation)
            cancel.raise_if_cancelled()
            budget.consume_step()
            if step.side_effecting:
                budget.consume_side_effect()
            current = self._attempt(plan, step, request_id, attempt, budget, cancel, confirmations)
            if current.pending is not None or current.status is StepStatus.CANCELLED:
                return current
            last = current
            if current.observation.code == ObservationCode.SUCCESS.value:
                self._loops.forget(current.reason_code or "")
                return current
            if not self._should_retry(step, current, attempt, maximum):
                return current
            budget.consume_retry()
            self._telemetry.counter("agent_retries_total")
            self._backoff(step.retry_policy.backoff_seconds * attempt, cancel, generation, budget)
        return last or StepExecution(step_id=step.step_id, status=StepStatus.FAILED,
                                     observation=build_observation(step.step_id,
                                                                   ObservationCode.EXECUTION_FAILED,
                                                                   "no attempt executed"),
                                     exhausted=True)

    def _should_retry(self, step: ValidatedStep, current: StepExecution, attempt: int,
                      maximum: int) -> bool:
        if attempt >= maximum or current.exhausted:
            return False
        if step.side_effecting:
            # A side effect may already have happened; never retry speculatively.
            return False
        return current.observation.code in set(step.retry_policy.retryable)

    def _backoff(self, delay: float, cancel: CancellationToken, generation: int, budget: Any) -> None:
        ceiling = min(max(0.0, delay), self._config.retry_backoff_ceiling_seconds)
        deadline = time.monotonic() + ceiling
        while time.monotonic() < deadline:
            self._control.require_current(generation)
            cancel.raise_if_cancelled()
            budget.check_deadline()
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    # --- one attempt ----------------------------------------------------
    def _attempt(self, plan: ValidatedPlan, step: ValidatedStep, request_id: str, attempt: int,
                 budget: Any, cancel: CancellationToken,
                 confirmations: ConfirmationProvider) -> StepExecution:
        signature = LoopDetector.signature(step.tool_id, step.operation, step.arguments_json)
        self._telemetry.counter("agent_steps_total")
        self._telemetry.emit(AgentEventType.STEP_STARTED, request_id=request_id,
                             plan_id=plan.plan_id, step_id=step.step_id, tool_id=step.tool_id,
                             operation=step.operation, state="executing")
        started = time.monotonic()
        request = self._request(step, request_id, plan, attempt)
        result = self._gateway.execute(request)
        if result.code is ExecutionCode.CONFIRMATION_REQUIRED:
            return self._await_confirmation(plan, step, request, attempt, confirmations, started)
        observation = observation_from_result(step.step_id, result)
        return self._finish(plan, step, request_id, observation, result, signature, attempt, started,
                            simulated=False)

    def _await_confirmation(self, plan: ValidatedPlan, step: ValidatedStep, request: ToolRequest,
                            attempt: int, confirmations: ConfirmationProvider,
                            started: float) -> StepExecution:
        token = _token_or_none(confirmations, step, request)
        if token is None:
            self._telemetry.emit(AgentEventType.AWAITING_CONFIRMATION, request_id=request.request_id,
                                 plan_id=plan.plan_id, step_id=step.step_id, tool_id=step.tool_id,
                                 operation=step.operation, state="awaiting_confirmation")
            observation = build_observation(step.step_id, ObservationCode.CONFIRMATION_REQUIRED,
                                            "explicit user confirmation required")
            return StepExecution(
                step_id=step.step_id, status=StepStatus.RUNNING, observation=observation,
                attempts=attempt, reason_code="confirmation_required",
                pending=PendingConfirmation(
                    request_id=request.request_id, step_id=step.step_id, tool_id=step.tool_id,
                    operation=step.operation, reason="explicit user confirmation required",
                ),
            )
        try:
            confirmed = request.model_copy(update={"confirmation_token": token})
            result = self._gateway.execute(confirmed)
        except Exception:
            result = ExecutionResult(code=ExecutionCode.DENIED, message="confirmation rejected")
        if result.code is ExecutionCode.CONFIRMATION_REQUIRED:
            result = ExecutionResult(code=ExecutionCode.DENIED, message="confirmation not accepted")
        observation = observation_from_result(step.step_id, result)
        signature = LoopDetector.signature(step.tool_id, step.operation, step.arguments_json)
        return self._finish(plan, step, request.request_id, observation, result, signature, attempt,
                            started, simulated=False)

    def _finish(self, plan: ValidatedPlan, step: ValidatedStep, request_id: str,
                observation: Observation, result: ExecutionResult, signature: str, attempt: int,
                started: float, simulated: bool) -> StepExecution:
        duration_ms = (time.monotonic() - started) * 1000
        success = result.success
        status = StepStatus.SUCCEEDED if success else StepStatus.FAILED
        if result.code is ExecutionCode.CANCELLED:
            status = StepStatus.CANCELLED
        self._telemetry.emit(AgentEventType.STEP_COMPLETED if success else AgentEventType.STEP_FAILED,
                             request_id=request_id, plan_id=plan.plan_id, step_id=step.step_id,
                             tool_id=step.tool_id, operation=step.operation,
                             state="observing" if success else "recovering", success=success,
                             reason_code=observation.code, duration_ms=duration_ms)
        self._telemetry.emit(AgentEventType.OBSERVED, request_id=request_id, plan_id=plan.plan_id,
                             step_id=step.step_id, tool_id=step.tool_id, operation=step.operation,
                             success=success, reason_code=observation.code)
        self._telemetry.audit_step(
            request_id=request_id, tool_id=step.tool_id, operation=step.operation,
            outcome=observation.code, authorization_level=self._gateway.catalog.authorization_level(step.tool_id),
            confirmation_state="CONSUMED_OR_NOT_REQUIRED" if success else "NOT_CONSUMED",
            allowed=success,
        )
        if not success:
            self._telemetry.counter("agent_step_failures_total")
            self._loops.record(signature, observation)
        return StepExecution(step_id=step.step_id, status=status, observation=observation,
                             attempts=attempt, reason_code=observation.code)

    # --- request construction -------------------------------------------
    def _request(self, step: ValidatedStep, request_id: str, plan: ValidatedPlan,
                 attempt: int) -> ToolRequest:
        level = self._gateway.catalog.authorization_level(step.tool_id)
        return ToolRequest(
            request_id=f"{request_id}.{step.step_id}.v{plan.version}.a{attempt}",
            tool_name=step.tool_id,
            operation=step.operation,
            authorization_level=level,
            arguments=step.argument_values(),
            originating_subsystem="agent.execution",
        )


def _status_for(observation: Observation) -> StepStatus:
    if observation.code == ObservationCode.SUCCESS.value:
        return StepStatus.SUCCEEDED
    return StepStatus.FAILED


def _token_or_none(provider: ConfirmationProvider, step: ValidatedStep,
                   request: ToolRequest) -> str | None:
    try:
        token = provider.resolve(step, request)
    except Exception:
        return None
    return token if isinstance(token, str) and token.strip() else None


@dataclass
class ExecutionTrace:
    """Bounded per-request execution bookkeeping."""

    limit: int = 64
    steps: list[StepExecution] = field(default_factory=list)

    def add(self, execution: StepExecution) -> None:
        self.steps.append(execution)
        del self.steps[:-max(1, self.limit)]

    def succeeded(self) -> tuple[str, ...]:
        return tuple(item.step_id for item in self.steps
                     if item.status is StepStatus.SUCCEEDED)
