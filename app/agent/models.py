"""Owned agent data. Neither plans, model output nor messages grant authority."""

from __future__ import annotations

import json
import math
import unicodedata
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Count = Annotated[int, Field(strict=True, ge=1, le=16)]


def now() -> datetime:
    return datetime.now(timezone.utc)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False)


class Priority(StrEnum):
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BACKGROUND = "background"


class State(StrEnum):
    IDLE = "idle"
    RECEIVED = "received"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"
    TIMED_OUT = "timed_out"


class Source(StrEnum):
    CLI = "cli"
    HUD = "hud"
    VOICE = "voice"
    API = "api"


class AgentRequest(Schema):
    request_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    session_id: Identifier
    user_input: str = Field(min_length=1, max_length=4096)
    source: Source = Source.CLI
    created_at: datetime = Field(default_factory=now)
    priority: Priority = Priority.NORMAL
    context_reference: Identifier | None = None
    cancellation_reference: Identifier | None = None

    @field_validator("user_input")
    @classmethod
    def safe_input(cls, value: str) -> str:
        if not value.strip() or any(
            unicodedata.category(c) in {"Cs", "Cc"} and c not in "\n\r\t" for c in value
        ):
            raise ValueError("invalid input text")
        if len(value.encode("utf-8")) > 16384:
            raise ValueError("input byte limit")
        return value

    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or not 1970 <= value.year <= 2100 or value > now():
            raise ValueError("invalid request timestamp")
        return value.astimezone(timezone.utc)


def owned_arguments(value: object) -> str:
    """Return canonical JSON, admitting only bounded primitive trees."""
    if isinstance(value, str):
        if len(value) > 8192:
            raise ValueError("argument size limit")
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise ValueError("invalid argument JSON") from None
    if not isinstance(value, dict):
        raise ValueError("arguments must be an object")
    remaining = 256

    def check(item: object, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 8:
            raise ValueError("argument structure limit")
        if item is None or type(item) in (bool, int):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("nonfinite argument")
            return
        if type(item) is str:
            if len(item) > 8192:
                raise ValueError("argument string limit")
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    raise ValueError("invalid argument key")
                check(child, depth + 1)
            return
        if type(item) in (list, tuple):
            for child in item:
                check(child, depth + 1)
            return
        raise ValueError("unsupported argument type")

    check(value)
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded) > 8192:
        raise ValueError("argument byte limit")
    return encoded


class RetryPolicy(Schema):
    """Bounded retries.

    `retryable` is an explicit allow-list of observation codes and is empty by
    default, so a plan must opt in to retries. The runtime separately refuses to
    retry any tool that may already have produced an external side effect.
    """

    max_attempts: int = Field(default=1, strict=True, ge=1, le=3)
    retryable: tuple[Identifier, ...] = Field(default=(), max_length=4)
    backoff_seconds: float = Field(default=0.25, strict=True, ge=0, le=5)
    cumulative_timeout_seconds: float = Field(default=30, strict=True, ge=1, le=120)


class VerificationKind(StrEnum):
    RESULT_CODE = "result_code"
    FIELD_PRESENT = "field_present"
    FIELD_EQUALS = "field_equals"
    FILE_EXISTS = "file_exists"
    MEMORY_EXISTS = "memory_exists"


class VerificationRule(Schema):
    kind: VerificationKind = VerificationKind.RESULT_CODE
    field: Identifier | None = None
    expected: str | None = Field(default=None, max_length=256)


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStep(Schema):
    step_id: Identifier
    tool_id: Identifier
    operation: Identifier
    arguments: str = "{}"
    dependencies: tuple[Identifier, ...] = Field(default=(), max_length=16)
    timeout: float = Field(default=30, strict=True, ge=1, le=120)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    expected_observation: str = Field(default="", max_length=256)
    verification_rule: VerificationRule = Field(default_factory=VerificationRule)
    status: StepStatus = StepStatus.PENDING

    @field_validator("arguments", mode="before")
    @classmethod
    def snapshot(cls, value: object) -> str:
        return owned_arguments(value)

    def argument_values(self) -> dict:
        """Fresh owned tree on each call; never a mutable field of a plan."""
        return json.loads(self.arguments)


class AgentPlan(Schema):
    plan_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    request_id: Identifier
    version: int = Field(default=1, strict=True, ge=1, le=4)
    objective: str = Field(min_length=1, max_length=1024)
    steps: tuple[AgentStep, ...] = Field(min_length=1, max_length=16)
    estimated_cost: float = Field(default=0, strict=True, ge=0, le=1000)
    status: State = State.PLANNING
    created_at: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def dag(self) -> AgentPlan:
        ids = {step.step_id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ValueError("duplicate step identifier")
        resolved: set[str] = set()
        for step in self.steps:
            if len(set(step.dependencies)) != len(step.dependencies) or not set(step.dependencies) <= ids:
                raise ValueError("invalid dependencies")
        for _ in self.steps:
            ready = {step.step_id for step in self.steps
                     if step.step_id not in resolved and set(step.dependencies) <= resolved}
            if not ready:
                break
            resolved.update(ready)
        if resolved != ids:
            raise ValueError("dependency cycle")
        return self


class Observation(Schema):
    step_id: Identifier
    code: Identifier
    summary: str = Field(default="", max_length=512)
    data_json: str = Field(default="{}", max_length=8192)
    simulated: StrictBool = False


class Verification(Schema):
    step_id: Identifier
    passed: StrictBool
    reason: str = Field(max_length=256)


class RecoveryStrategy(StrEnum):
    """Bounded recovery options. No rollback is invented where none exists."""

    RETRY = "retry"
    ALTERNATIVE_STEP = "alternative_step"
    ROLLBACK_IF_SUPPORTED = "rollback_if_supported"
    ESCALATE_TO_USER = "escalate_to_user"
    STOP = "stop"


class Escalation(Schema):
    """Bounded human handoff. Explains a stop; never fabricates completion."""

    request_id: Identifier
    step_id: Identifier | None = None
    attempted: str = Field(default="", max_length=512)
    happened: str = Field(default="", max_length=512)
    remaining: tuple[Identifier, ...] = Field(default=(), max_length=16)
    stopped_because: str = Field(default="", max_length=256)
    required_user_action: str = Field(default="", max_length=512)


def safe_summary(text: object, limit: int = 512) -> str:
    """Printable-only, length-bounded text for model-visible summaries."""
    cleaned = "".join(c for c in str(text if text is not None else "") if c.isprintable() or c == " ")
    return cleaned[:limit]


class ObservationCode(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    INVALID_REQUEST = "invalid_request"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_REJECTED = "confirmation_rejected"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    BUDGET_EXCEEDED = "budget_exceeded"
    LOOP_DETECTED = "loop_detected"
    MODEL_UNAVAILABLE = "model_unavailable"
    GATEWAY_ERROR = "gateway_error"
    DUPLICATE = "duplicate"


def build_observation(step_id: str, code: object, summary: object = "",
                      data: object = None, simulated: bool = False) -> Observation:
    """Construct a bounded observation from untrusted tool output."""
    try:
        payload = owned_arguments(data if isinstance(data, dict) else {})
    except (ValueError, TypeError, RecursionError):
        payload = "{}"
    return Observation(
        step_id=step_id,
        code=str(getattr(code, "value", code)),
        summary=safe_summary(summary),
        data_json=payload,
        simulated=bool(simulated),
    )


class StepOutcome(Schema):
    step_id: Identifier
    status: StepStatus
    observation: Observation
    verification: Verification | None = None
    attempts: int = Field(default=1, strict=True, ge=1, le=8)
    recovery: RecoveryStrategy | None = None
    cancellation_pending: StrictBool = False
    escalation: Escalation | None = None


class PreviewStep(Schema):
    step_id: Identifier
    tool_id: Identifier
    operation: Identifier
    decision: str = Field(default="", max_length=32)
    authorization_level: str | None = Field(default=None, max_length=32)
    requires_confirmation: bool = False
    verification: VerificationKind = VerificationKind.RESULT_CODE
    simulated: StrictBool = False


class PlanPreview(Schema):
    request_id: Identifier
    plan_id: Identifier
    objective: str = Field(min_length=1, max_length=1024)
    steps: tuple[PreviewStep, ...] = Field(default=(), max_length=16)
    policy_requirements: tuple[str, ...] = Field(default=(), max_length=16)
    confirmation_requirements: tuple[Identifier, ...] = Field(default=(), max_length=16)
    estimated_steps: int = Field(default=0, strict=True, ge=0, le=256)
    estimated_side_effects: int = Field(default=0, strict=True, ge=0, le=256)
    estimated_runtime_seconds: float = Field(default=0, strict=True, ge=0, le=600)
    executed: StrictBool = False


class PendingConfirmation(Schema):
    request_id: Identifier
    step_id: Identifier
    tool_id: Identifier
    operation: Identifier
    authorization_level: str | None = Field(default=None, max_length=32)
    reason: str = Field(default="", max_length=256)


class RuntimeState(StrEnum):
    INITIALIZING = "initializing"
    READY = "ready"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DRAINING = "draining"
    STOPPED = "stopped"


class AgentStatus(Schema):
    control_state: str = Field(default="enabled", max_length=16)
    control_generation: int = Field(default=0, strict=True, ge=0)
    runtime_state: str = Field(default="initializing", max_length=32)
    queued: int = Field(default=0, strict=True, ge=0)
    active: int = Field(default=0, strict=True, ge=0)
    active_steps: int = Field(default=0, strict=True, ge=0)
    sessions: int = Field(default=0, strict=True, ge=0)
    total_requests: int = Field(default=0, strict=True, ge=0)
    completed: int = Field(default=0, strict=True, ge=0)
    failed: int = Field(default=0, strict=True, ge=0)
    cancelled: int = Field(default=0, strict=True, ge=0)
    plan_rejections: int = Field(default=0, strict=True, ge=0)
    steps_executed: int = Field(default=0, strict=True, ge=0)
    step_failures: int = Field(default=0, strict=True, ge=0)
    replans: int = Field(default=0, strict=True, ge=0)
    retries: int = Field(default=0, strict=True, ge=0)
    gateway_available: StrictBool = False
    memory_available: StrictBool = False
    model_available: StrictBool = False
    available_capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    unavailable_capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    degraded: tuple[str, ...] = Field(default=(), max_length=16)


class AgentResult(Schema):
    request_id: Identifier
    plan_id: Identifier | None = None
    plan_version: int | None = Field(default=None, strict=True, ge=1, le=4)
    status: State
    completed_steps: tuple[Identifier, ...] = Field(default=(), max_length=16)
    failed_step: Identifier | None = None
    output: str = Field(default="", max_length=8192)
    observations: tuple[Observation, ...] = Field(default=(), max_length=16)
    verification: tuple[Verification, ...] = Field(default=(), max_length=16)
    duration: float = Field(default=0, ge=0)
    recovery: str = Field(default="", max_length=256)
    cancellation_pending: StrictBool = False
    escalation: Escalation | None = None
    degraded: tuple[str, ...] = Field(default=(), max_length=16)


class AgentSession(Schema):
    session_id: Identifier
    created_at: datetime = Field(default_factory=now)
    request_count: int = Field(default=0, strict=True, ge=0, le=128)
    active: StrictBool = False


class Role(StrEnum):
    COORDINATOR = "coordinator"
    PLANNER = "planner"
    RESEARCH = "research"
    MEMORY = "memory"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    VISION = "vision"
    CODING = "coding"
    VOICE = "voice"


class MessageType(StrEnum):
    TASK = "task"
    OBSERVATION = "observation"
    RESULT = "result"
    ESCALATION = "escalation"


class AgentMessage(Schema):
    sender: Role
    recipient: Role
    request_id: Identifier
    task_id: Identifier
    message_type: MessageType
    payload: str = Field(default="", max_length=2048)
    timestamp: datetime = Field(default_factory=now)
    correlation_id: Identifier = Field(default_factory=lambda: uuid4().hex)
