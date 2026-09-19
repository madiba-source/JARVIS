"""Validate a whole plan before any step is attempted.

Validation answers one question: *could* this plan execute at all? It is not
authorization. Passing validation means the tools exist, the operations are
registered, the arguments satisfy the trusted schemas, the dependency graph is a
DAG, and the plan fits the configured budgets. Every step still has to cross the
policy checkpoint on its own.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, StrictBool

from .catalog import ToolCatalog
from .config import AgentConfig
from .errors import PlanValidationError
from .models import AgentPlan, AgentStep, RetryPolicy, Schema, VerificationKind, VerificationRule

MAX_RETRY_ATTEMPTS = 3
MAX_IDENTICAL_SIDE_EFFECTS = 16


class ValidatedStep(Schema):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    tool_id: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=64)
    arguments_json: str = Field(default="{}", max_length=8192)
    dependencies: tuple[str, ...] = Field(default=(), max_length=16)
    timeout: float = Field(default=30, strict=True, ge=1, le=120)
    verification_rule: VerificationRule = Field(default_factory=VerificationRule)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    side_effecting: StrictBool = False
    requires_confirmation: StrictBool = False

    def argument_values(self) -> dict[str, Any]:
        return json.loads(self.arguments_json)


class ValidatedPlan(Schema):
    plan_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=64)
    version: int = Field(default=1, strict=True, ge=1, le=4)
    objective: str = Field(min_length=1, max_length=1024)
    steps: tuple[ValidatedStep, ...] = Field(min_length=1, max_length=16)
    step_count: int = Field(default=0, strict=True, ge=0, le=16)
    side_effects: int = Field(default=0, strict=True, ge=0, le=16)
    estimated_runtime_seconds: float = Field(default=0, strict=True, ge=0, le=600)
    authorization_levels: tuple[int, ...] = Field(default=(), max_length=16)
    requires_confirmation: StrictBool = False

    def step(self, step_id: str) -> ValidatedStep | None:
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        return None

    def objective_view(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "version": self.version,
            "steps": [{"step_id": step.step_id, "tool_id": step.tool_id,
                       "operation": step.operation} for step in self.steps],
        }


def validate_plan(plan: AgentPlan, catalog: ToolCatalog, config: AgentConfig) -> ValidatedPlan:
    """Validate and normalize a model-proposed plan. Raises `PlanRejected`."""
    if not isinstance(plan, AgentPlan):
        raise PlanValidationError("plan is not a typed agent plan")
    if len(plan.steps) > config.max_plan_steps:
        raise PlanValidationError("plan exceeds the step limit")
    if len(plan.steps) > config.max_total_steps:
        raise PlanValidationError("plan exceeds the total step budget")
    steps = tuple(_validate_step(step, catalog, config) for step in plan.steps)
    _validate_graph(steps)
    side_effects = sum(1 for step in steps if step.side_effecting)
    if side_effects > MAX_IDENTICAL_SIDE_EFFECTS:
        raise PlanValidationError("plan exceeds the side effect limit")
    return ValidatedPlan(
        plan_id=plan.plan_id,
        request_id=plan.request_id,
        version=plan.version,
        objective=plan.objective,
        steps=steps,
        step_count=len(steps),
        side_effects=side_effects,
        estimated_runtime_seconds=round(sum(step.timeout for step in steps), 3),
        authorization_levels=tuple(int(catalog.authorization_level(step.tool_id) or 0) for step in steps),
        requires_confirmation=any(step.requires_confirmation for step in steps),
    )


def _validate_step(step: AgentStep, catalog: ToolCatalog, config: AgentConfig) -> ValidatedStep:
    view = catalog.require_view(step.tool_id)
    if not catalog.has_operation(step.tool_id, step.operation):
        raise PlanValidationError("step operation is not registered for that tool")
    if step.timeout > config.max_step_seconds:
        raise PlanValidationError("step timeout exceeds the configured maximum")
    _validate_retry(step.retry_policy, config)
    _validate_verification(step.verification_rule)
    try:
        normalized = catalog.validate_arguments(step.tool_id, step.operation, step.argument_values())
    except PlanValidationError:
        raise
    except Exception:
        raise PlanValidationError("step arguments are not valid for the operation") from None
    return ValidatedStep(
        step_id=step.step_id,
        tool_id=step.tool_id,
        operation=step.operation,
        arguments_json=json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False),
        dependencies=tuple(step.dependencies),
        timeout=step.timeout,
        verification_rule=step.verification_rule,
        retry_policy=step.retry_policy,
        side_effecting=view.side_effecting,
        requires_confirmation=view.requires_confirmation,
    )


def _validate_retry(policy: RetryPolicy, config: AgentConfig) -> None:
    if policy.max_attempts > MAX_RETRY_ATTEMPTS:
        raise PlanValidationError("retry attempts exceed the maximum")
    if policy.backoff_seconds > config.retry_backoff_ceiling_seconds:
        raise PlanValidationError("retry backoff exceeds the configured ceiling")
    if policy.max_attempts > 1 and not policy.retryable:
        raise PlanValidationError("retries require an explicit list of retryable outcomes")
    if policy.cumulative_timeout_seconds > config.max_runtime_seconds:
        raise PlanValidationError("retry budget exceeds the runtime budget")


def _validate_verification(rule: VerificationRule) -> None:
    if rule.kind in (VerificationKind.FIELD_PRESENT, VerificationKind.FIELD_EQUALS) and not rule.field:
        raise PlanValidationError("verification rule requires a field name")
    if rule.kind is VerificationKind.FIELD_EQUALS and rule.expected is None:
        raise PlanValidationError("field comparison requires an expected value")


def _validate_graph(steps: tuple[ValidatedStep, ...]) -> None:
    ids = {step.step_id for step in steps}
    if len(ids) != len(steps):
        raise PlanValidationError("duplicate step identifier")
    for step in steps:
        if not set(step.dependencies) <= ids:
            raise PlanValidationError("step depends on an unknown step")
    resolved: set[str] = set()
    for _ in steps:
        ready = {step.step_id for step in steps
                 if step.step_id not in resolved and set(step.dependencies) <= resolved}
        if not ready:
            break
        resolved |= ready
    if resolved != ids:
        raise PlanValidationError("dependency cycle")
