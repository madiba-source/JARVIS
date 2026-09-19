"""Deterministic verification of what actually happened.

"the process exited 0" is not evidence that the task happened. Where an outcome
is observable, verification checks the observation, and where an outcome needs
the real world it asks a Phase 04/05 probe through the same policy gateway.

Probes are read-only and never authoritative: an inconclusive probe reports
`probe_unavailable` and verification fails closed rather than claiming success.
"""

from __future__ import annotations

import json
from typing import Any

from app.policy.enums import AuthorizationLevel
from app.policy.models import ToolRequest

from .errors import GatewayUnavailable
from .gateway import ExecutionGateway
from .memory_access import MemoryAccessor
from .models import Observation, ObservationCode, Verification, VerificationKind
from .plan_validation import ValidatedStep

FILE_TOOL = "filesystem"
STAT_OPERATION = "stat_path"
SUCCESS_CODE = ObservationCode.SUCCESS.value
MAX_FIELD_DEPTH = 4
_MISSING = object()


class GatewayProbes:
    """Read-only world probes routed through the policy gateway."""

    def __init__(self, gateway: ExecutionGateway, memory: MemoryAccessor | None = None) -> None:
        self._gateway = gateway
        self._memory = memory

    def file_exists(self, path: str) -> bool | None:
        if not self._gateway.catalog.has_operation(FILE_TOOL, STAT_OPERATION):
            return None
        try:
            request = ToolRequest(
                request_id="verify-stat",
                tool_name=FILE_TOOL,
                operation=STAT_OPERATION,
                authorization_level=AuthorizationLevel.L0_READ_ONLY,
                arguments={"path": str(path)[:4096]},
                originating_subsystem="agent.verification",
            )
            result = self._gateway.execute(request)
        except GatewayUnavailable:
            return None
        if not result.success:
            # A missing path is a definite negative; anything else is unknown.
            return False if result.code.value in {"execution_failed", "invalid_request"} else None
        return bool(isinstance(result.data, dict) and result.data.get("is_file"))

    def memory_exists(self, text: str) -> bool | None:
        if self._memory is None:
            return None
        return self._memory.exists(str(text)[:512], "verify-memory")


class Verifier:
    """Evaluates one step's declared verification rule."""

    def __init__(self, probes: GatewayProbes | None = None) -> None:
        self._probes = probes

    def verify(self, step: ValidatedStep, observation: Observation) -> Verification:
        rule = step.verification_rule
        try:
            passed, reason = self._evaluate(rule.kind, rule.field, rule.expected, observation)
        except Exception:
            passed, reason = False, "verification_error"
        return Verification(step_id=step.step_id, passed=passed, reason=reason)

    def _evaluate(self, kind: VerificationKind, field: str | None, expected: str | None,
                  observation: Observation) -> tuple[bool, str]:
        if kind is VerificationKind.RESULT_CODE:
            return observation.code == SUCCESS_CODE, "result_code"
        if kind is VerificationKind.FIELD_PRESENT:
            return self._field_present(observation, field)
        if kind is VerificationKind.FIELD_EQUALS:
            return self._field_equals(observation, field, expected)
        if kind is VerificationKind.FILE_EXISTS:
            return self._file_exists(observation, field, expected)
        if kind is VerificationKind.MEMORY_EXISTS:
            return self._memory_exists(observation, field, expected)
        return False, "unknown_rule"

    def _field_present(self, observation: Observation, field: str | None) -> tuple[bool, str]:
        found = _lookup(_data(observation), field) is not _MISSING
        return found, "field_present" if found else "field_missing"

    def _field_equals(self, observation: Observation, field: str | None,
                      expected: str | None) -> tuple[bool, str]:
        found = _lookup(_data(observation), field)
        if found is _MISSING:
            return False, "field_missing"
        return (str(found) == str(expected)), "field_equals" if str(found) == str(expected) else "field_mismatch"

    def _file_exists(self, observation: Observation, field: str | None,
                     expected: str | None) -> tuple[bool, str]:
        if self._probes is None:
            return False, "probe_unavailable"
        path = _probe_target(observation, field, expected)
        if path is None:
            return False, "probe_target_missing"
        exists = self._probes.file_exists(path)
        if exists is None:
            return False, "probe_unavailable"
        return exists, "file_present" if exists else "file_absent"

    def _memory_exists(self, observation: Observation, field: str | None,
                       expected: str | None) -> tuple[bool, str]:
        if self._probes is None:
            return False, "probe_unavailable"
        text = _probe_target(observation, field, expected)
        if text is None:
            return False, "probe_target_missing"
        exists = self._probes.memory_exists(text)
        if exists is None:
            return False, "probe_unavailable"
        return exists, "memory_present" if exists else "memory_absent"


def _data(observation: Observation) -> Any:
    try:
        return json.loads(observation.data_json)
    except (ValueError, RecursionError):
        return {}


def _probe_target(observation: Observation, field: str | None, expected: str | None) -> str | None:
    """Prefer an expected literal, else the named observation field."""
    for candidate in (expected, _lookup(_data(observation), field)):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _lookup(data: Any, path: str | None, depth: int = 0) -> Any:
    if not path or depth > MAX_FIELD_DEPTH:
        return _MISSING
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current
