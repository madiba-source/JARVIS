"""Authoritative, bounded coordinator for one agent request at a time."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .budget import BudgetTracker
from .cancel import CancellationToken
from .confirmation import ConfirmationProvider, DenyConfirmationProvider
from .config import AgentConfig
from .control import AgentControl, ControlSnapshot, ControlState
from .errors import AgentCancelled, BudgetExceeded, DisabledError, PlanRejected, RuntimeDeadlineExceeded
from .events import AgentEventType
from .execution import ExecutionTrace, StepExecution, StepExecutor
from .gateway import ExecutionGateway
from .idempotency import IdempotencyRegistry
from .loop import LoopDetector
from .memory_access import MemoryAccessor
from .models import AgentRequest, AgentResult, AgentSession, AgentStatus, Observation, RecoveryStrategy, State, Verification
from .planner import Planner
from .recovery import RecoveryEngine
from .router import ModelRouter
from .telemetry import AgentTelemetry
from .verification import GatewayProbes, Verifier
from .state import StateMachine
from .context import ContextAssembler


@dataclass
class _ActiveRequest:
    request: AgentRequest
    token: CancellationToken
    machine: StateMachine
    budget: BudgetTracker


class AgentRuntime:
    """Compose Phase 06 without creating a second authority boundary."""

    def __init__(self, policy_service: Any, *, config: AgentConfig | None = None,
                 router: ModelRouter | None = None, control: AgentControl | None = None,
                 telemetry: AgentTelemetry | None = None,
                 confirmations: ConfirmationProvider | None = None) -> None:
        self.config = config or AgentConfig()
        self.gateway = ExecutionGateway(policy_service, max_concurrency=self.config.max_parallel_steps)
        self.control = control or AgentControl(
            ControlState.ENABLED if self.config.enabled else ControlState.DISABLED
        )
        self.router = router or ModelRouter(self.config)
        self.telemetry = telemetry or AgentTelemetry(audit_sink=self.gateway)
        self.memory = MemoryAccessor(self.gateway)
        self.assembler = ContextAssembler(self.config, self.memory)
        self.planner = Planner(self.config, self.router, self.gateway.catalog, self.assembler)
        self.verifier = Verifier(GatewayProbes(self.gateway, self.memory))
        self.recovery = RecoveryEngine(self.config)
        self._registry = IdempotencyRegistry()
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveRequest] = {}
        self._sessions: dict[str, AgentSession] = {}
        self._runtime_state = "ready" if self.router.available() else "degraded"
        self._counts = {"total": 0, "completed": 0, "failed": 0, "cancelled": 0,
                        "plan_rejections": 0, "steps": 0, "step_failures": 0,
                        "replans": 0, "retries": 0}
        self.control.subscribe(self._on_control_change)
        self.gateway.set_active(self.control.enabled)

    def submit(self, request: AgentRequest, *, confirmations: ConfirmationProvider | None = None) -> AgentResult:
        """Run one request through planning, policy execution, and verification."""
        started = time.monotonic()
        with self._lock:
            if not self.config.enabled or not self.control.enabled:
                return self._result(request, State.DISABLED, started, degraded=("disabled",))
            if self._active:
                return self._result(request, State.FAILED, started, output="agent capacity is busy",
                                    degraded=("active_request_limit",))
            self.control.require_enabled()
            if len(self._sessions) >= self.config.max_sessions and request.session_id not in self._sessions:
                return self._result(request, State.FAILED, started, output="session capacity is full",
                                    degraded=("session_limit",))
            token = CancellationToken()
            active = _ActiveRequest(request, token, StateMachine(), BudgetTracker(self.config))
            self._active[request.request_id] = active
            session = self._sessions.setdefault(request.session_id, AgentSession(session_id=request.session_id))
            self._sessions[request.session_id] = session.model_copy(
                update={"request_count": session.request_count + 1, "active": True}
            )
            self._counts["total"] += 1
        self.telemetry.counter("agent_requests_total")
        self.telemetry.gauge("agent_active", 1)
        self.telemetry.emit(AgentEventType.REQUESTED, request_id=request.request_id)
        try:
            return self._run(active, started, confirmations or DenyConfirmationProvider())
        finally:
            with self._lock:
                self._active.pop(request.request_id, None)
                session = self._sessions.get(request.session_id)
                if session is not None:
                    self._sessions[request.session_id] = session.model_copy(update={"active": False})
            self.telemetry.gauge("agent_active", 0)

    def _run(self, active: _ActiveRequest, started: float,
             confirmations: ConfirmationProvider) -> AgentResult:
        request, token, machine, budget = active.request, active.token, active.machine, active.budget
        trace = ExecutionTrace(limit=self.config.max_observations)
        verifications: list[Verification] = []
        try:
            machine.to(State.RECEIVED)
            machine.to(State.PLANNING)
            self.telemetry.emit(AgentEventType.PLANNING, request_id=request.request_id, state="planning")
            plan = self.planner.plan(request, budget, token).plan
            self.telemetry.emit(AgentEventType.PLANNED, request_id=request.request_id,
                                plan_id=plan.plan_id, state="planned")
            execution = StepExecutor(self.config, self.gateway, self.telemetry, self.control,
                                     self._registry, LoopDetector(self.config))
            completed: list[str] = []
            replans = 0
            while True:
                machine.to(State.EXECUTING)
                outcome = self._execute_plan(plan, execution, request, token, budget, confirmations,
                                             completed, trace, verifications, machine)
                if outcome is not None:
                    return self._finish(outcome, started)
                if len(completed) == len(plan.steps):
                    machine.to(State.COMPLETED)
                    self._counts["completed"] += 1
                    self.telemetry.counter("agent_completed_total")
                    return self._result(request, State.COMPLETED, started, plan=plan,
                                        completed=completed, observations=trace.steps,
                                        verification=verifications)
                replans += 1
                budget.consume_replan()
                self._counts["replans"] += 1
                self.telemetry.counter("agent_replans_total")
                machine.to(State.RECOVERING)
                self.telemetry.emit(AgentEventType.REPLANNED, request_id=request.request_id,
                                    plan_id=plan.plan_id, state="recovering")
                plan = self.planner.plan(
                    request, budget, token,
                    observations=tuple(item.observation.model_dump(mode="json") for item in trace.steps),
                    previous=plan, failure_code="verification_failed",
                ).plan
                completed.clear()
                if replans > self.config.max_replans:
                    raise BudgetExceeded("replan budget exceeded")
        except (AgentCancelled, DisabledError):
            target = State.DISABLED if self.control.disabled else State.CANCELLED
            self._settle(machine, target)
            self._counts["cancelled"] += 1
            self.telemetry.counter("agent_cancelled_total")
            return self._result(request, target, started, observations=trace.steps)
        except (RuntimeDeadlineExceeded, BudgetExceeded):
            self._settle(machine, State.TIMED_OUT)
            self._counts["failed"] += 1
            return self._result(request, State.TIMED_OUT, started, observations=trace.steps)
        except PlanRejected:
            self._settle(machine, State.FAILED)
            self._counts["plan_rejections"] += 1
            self.telemetry.counter("agent_plan_rejections_total")
            return self._result(request, State.FAILED, started, degraded=("plan_rejected",))
        except Exception:
            self._settle(machine, State.FAILED)
            self._counts["failed"] += 1
            self.telemetry.counter("agent_failed_total")
            return self._result(request, State.FAILED, started, degraded=("runtime_failure",))

    def _execute_plan(self, plan: Any, execution: StepExecutor, request: AgentRequest,
                      token: CancellationToken, budget: BudgetTracker,
                      confirmations: ConfirmationProvider, completed: list[str],
                      trace: ExecutionTrace, verifications: list[Verification],
                      machine: StateMachine) -> AgentResult | None:
        pending = [step for step in plan.steps if step.step_id not in completed]
        while pending:
            token.raise_if_cancelled()
            budget.check_deadline()
            ready = next((step for step in pending if set(step.dependencies) <= set(completed)), None)
            if ready is None:
                return self._result(request, State.FAILED, time.monotonic(), output="dependency graph stalled")
            current = execution.execute(plan, ready, request_id=request.request_id,
                                        generation=self.control.generation, budget=budget,
                                        cancel=token, confirmations=confirmations)
            trace.add(current)
            self._counts["steps"] += current.attempts
            self._counts["retries"] += max(0, current.attempts - 1)
            if current.pending is not None:
                self._settle(machine, State.AWAITING_CONFIRMATION)
                self.telemetry.emit(AgentEventType.AWAITING_CONFIRMATION,
                                    request_id=request.request_id, plan_id=plan.plan_id,
                                    step_id=ready.step_id, state="awaiting_confirmation")
                return self._result(request, State.AWAITING_CONFIRMATION, time.monotonic(),
                                    plan=plan, observations=trace.steps, failed_step=ready.step_id)
            machine.to(State.OBSERVING)
            machine.to(State.VERIFYING)
            verification = self.verifier.verify(ready, current.observation)
            verifications.append(verification)
            if verification.passed and current.status.value == "succeeded":
                completed.append(ready.step_id)
                pending.remove(ready)
                continue
            self._counts["step_failures"] += 1
            self.telemetry.counter("agent_step_failures_total")
            decision = self.recovery.decide(ready, current, request_id=request.request_id,
                                             remaining=tuple(item.step_id for item in pending),
                                             replans_used=int(budget.snapshot()["replans"]))
            if decision.strategy is RecoveryStrategy.ALTERNATIVE_STEP:
                return None
            self._settle(machine, State.FAILED)
            return self._result(request, State.FAILED, time.monotonic(), plan=plan,
                                observations=trace.steps, verification=verifications,
                                failed_step=ready.step_id, output=decision.reason_code,
                                escalation=decision.escalation)
        return None

    def cancel(self, request_id: str | None = None, reason: str = "cancelled") -> bool:
        with self._lock:
            targets = tuple(self._active.values()) if request_id is None else tuple(
                item for key, item in self._active.items() if key == request_id
            )
        changed = False
        for active in targets:
            changed = active.token.cancel(reason) or changed
        return changed

    def pause(self) -> ControlSnapshot:
        snapshot = self.control.pause()
        self.telemetry.emit(AgentEventType.PAUSED, state="paused")
        return snapshot

    def resume(self) -> ControlSnapshot:
        snapshot = self.control.resume()
        self.gateway.set_active(True)
        self.telemetry.emit(AgentEventType.RESUMED, state="enabled")
        return snapshot

    def disable(self) -> ControlSnapshot:
        snapshot = self.control.disable()
        self.cancel(reason="disabled")
        self.gateway.set_active(False)
        return snapshot

    def enable(self) -> ControlSnapshot:
        snapshot = self.control.enable()
        self.gateway.set_active(True)
        return snapshot

    def status(self) -> AgentStatus:
        with self._lock:
            active = len(self._active)
            sessions = len(self._sessions)
            counts = dict(self._counts)
        return AgentStatus(
            control_state=self.control.state.value, control_generation=self.control.generation,
            runtime_state=self._runtime_state, queued=0, active=active, active_steps=0,
            sessions=sessions, total_requests=counts["total"], completed=counts["completed"],
            failed=counts["failed"], cancelled=counts["cancelled"],
            plan_rejections=counts["plan_rejections"], steps_executed=counts["steps"],
            step_failures=counts["step_failures"], replans=counts["replans"], retries=counts["retries"],
            gateway_available=self.gateway.available, memory_available=self.memory.readable,
            model_available=self.router.available(), available_capabilities=self.gateway.catalog.tool_ids,
        )

    def close(self) -> None:
        self.disable()
        self.gateway.close()
        self.router.close()
        with self._lock:
            self._runtime_state = "stopped"

    def _on_control_change(self, snapshot: ControlSnapshot) -> None:
        if snapshot.state is ControlState.DISABLED:
            self.cancel(reason="disabled")
            self.gateway.set_active(False)
            self.telemetry.emit(AgentEventType.DISABLED, state="disabled")

    @staticmethod
    def _settle(machine: StateMachine, target: State) -> None:
        if not machine.is_terminal:
            try:
                machine.to(target)
            except ValueError:
                pass

    def _finish(self, result: AgentResult, started: float) -> AgentResult:
        return result.model_copy(update={"duration": max(result.duration, time.monotonic() - started)})

    @staticmethod
    def _result(request: AgentRequest, status: State, started: float, *, plan: Any = None,
                completed: list[str] | tuple[str, ...] = (), failed_step: str | None = None,
                output: str = "", observations: Any = (), verification: Any = (),
                escalation: Any = None, degraded: tuple[str, ...] = ()) -> AgentResult:
        return AgentResult(
            request_id=request.request_id, plan_id=getattr(plan, "plan_id", None),
            plan_version=getattr(plan, "version", None), status=status,
            completed_steps=tuple(completed)[:16], failed_step=failed_step,
            output=str(output)[:8192], observations=tuple(
                item.observation for item in observations[-16:] if isinstance(item, StepExecution)
            ), verification=tuple(verification)[-16:], duration=max(0.0, time.monotonic() - started),
            escalation=escalation, degraded=degraded,
        )


AgentObservation = Observation
AgentVerification = Verification