"""Strict schema for model-proposed plans, and its parser.

The model returns data. This module converts that data into a typed plan or
rejects it, and it is deliberately unforgiving:

* exactly one JSON object, nothing around it;
* unknown fields rejected (`extra="forbid"`);
* no executable code, no shell fragments, no serialised callables;
* argument trees bounded by the same owned-argument rules as tool steps;
* step and byte counts bounded before anything else is considered.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, field_validator

from .errors import ModelOutputInvalid
from .models import Identifier, RetryPolicy, Schema, VerificationKind, VerificationRule, owned_arguments

MAX_STEPS = 16
MAX_TEXT_BYTES = 32768


class PlannerVerification(Schema):
    kind: VerificationKind = VerificationKind.RESULT_CODE
    field: Identifier | None = None
    expected: str | None = Field(default=None, max_length=256)

    def to_rule(self) -> VerificationRule:
        return VerificationRule(kind=self.kind, field=self.field, expected=self.expected)


class PlannerStep(Schema):
    step_id: Identifier
    tool_id: Identifier
    operation: Identifier
    arguments: str = "{}"
    dependencies: tuple[Identifier, ...] = Field(default=(), max_length=16)
    timeout: float = Field(default=30, strict=True, ge=1, le=120)
    max_attempts: int = Field(default=1, strict=True, ge=1, le=3)
    retryable: tuple[Identifier, ...] = Field(default=(), max_length=4)
    expected_observation: str = Field(default="", max_length=256)
    verification: PlannerVerification = Field(default_factory=PlannerVerification)

    @field_validator("arguments", mode="before")
    @classmethod
    def capture(cls, value: object) -> str:
        return owned_arguments(value)

    def argument_values(self) -> dict[str, Any]:
        return json.loads(self.arguments)

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(max_attempts=self.max_attempts, retryable=self.retryable,
                           backoff_seconds=0.05)


class PlannerOutput(Schema):
    objective: str = Field(min_length=1, max_length=1024)
    steps: tuple[PlannerStep, ...] = Field(min_length=1, max_length=MAX_STEPS)


def parse_plan_text(text: object, *, max_bytes: int = MAX_TEXT_BYTES,
                    max_steps: int = MAX_STEPS) -> PlannerOutput:
    """Parse exactly one JSON plan object. Raises `ModelOutputInvalid`."""
    if not isinstance(text, str) or not text.strip():
        raise ModelOutputInvalid("model returned no plan text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise ModelOutputInvalid("model output is not encodable") from None
    if size > max_bytes:
        raise ModelOutputInvalid("model output exceeds the byte limit")
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ModelOutputInvalid("model output is not a single JSON object")
    try:
        payload = json.loads(stripped)
    except (ValueError, RecursionError):
        raise ModelOutputInvalid("model output is not valid JSON") from None
    if not isinstance(payload, dict):
        raise ModelOutputInvalid("model output is not a JSON object")
    try:
        output = PlannerOutput.model_validate(payload)
    except Exception:
        # Validator detail is never surfaced: it can echo model-supplied values.
        raise ModelOutputInvalid("model output does not match the required schema") from None
    if len(output.steps) > max_steps:
        raise ModelOutputInvalid("model plan exceeds the step limit")
    _reject_duplicate_ids(output)
    return output


def _reject_duplicate_ids(output: PlannerOutput) -> None:
    seen: set[str] = set()
    for step in output.steps:
        if step.step_id in seen:
            raise ModelOutputInvalid("model plan repeats a step identifier")
        seen.add(step.step_id)


PLAN_SCHEMA_HINT = json.dumps({
    "objective": "one short sentence",
    "steps": [{
        "step_id": "s1",
        "tool_id": "registered tool id from TOOLS",
        "operation": "registered operation for that tool",
        "arguments": {"argument": "value"},
        "dependencies": [],
        "timeout": 30,
        "max_attempts": 1,
        "retryable": [],
        "expected_observation": "what should be true afterwards",
        "verification": {"kind": "result_code", "field": None, "expected": None},
    }],
}, ensure_ascii=True, separators=(",", ":"))
