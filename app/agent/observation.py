"""Turn a typed tool result into a bounded observation.

A tool result is untrusted data. Only bounded, structure-preserving content
reaches the observation: status code, small structured data, exit code and the
*size* of captured streams plus a short printable preview. Full raw output is
never promoted into model context by default.
"""

from __future__ import annotations

from typing import Any

from app.execution.models import ExecutionResult

from .models import Observation, ObservationCode, build_observation, safe_summary

MAX_PREVIEW_CHARS = 256
MAX_DATA_ENTRIES = 32
MAX_DATA_DEPTH = 4


def observation_from_result(step_id: str, result: ExecutionResult,
                            simulated: bool = False) -> Observation:
    """Build a bounded observation from one tool result."""
    data = _bounded_data(result.data)
    if result.exit_code is not None:
        data["exit_code"] = int(result.exit_code)
    data["stdout_bytes"] = len(result.stdout)
    data["stderr_bytes"] = len(result.stderr)
    preview = safe_summary(result.stdout, MAX_PREVIEW_CHARS)
    if preview:
        data["stdout_preview"] = preview
    error_preview = safe_summary(result.stderr, MAX_PREVIEW_CHARS)
    if error_preview:
        data["stderr_preview"] = error_preview
    data["code"] = result.code.value
    return build_observation(
        step_id=step_id,
        code=result.code.value if result.success else _failure_code(result),
        summary=result.message,
        data=data,
        simulated=simulated,
    )


def _failure_code(result: ExecutionResult) -> str:
    """Keep the tool's own code; only unknown codes collapse to a fixed value."""
    code = result.code.value
    known = {item.value for item in ObservationCode}
    return code if code in known else ObservationCode.EXECUTION_FAILED.value


def _bounded_data(value: Any, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if depth > MAX_DATA_DEPTH:
        return {}
    bounded: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= MAX_DATA_ENTRIES or not isinstance(key, str) or len(key) > 64:
            break
        bounded[key[:64]] = _bounded_value(item, depth + 1)
    return bounded


def _bounded_value(item: Any, depth: int) -> Any:
    if item is None or type(item) in (bool, int):
        return item
    if type(item) is float:
        return item
    if type(item) is str:
        return item[:512]
    if isinstance(item, dict) and depth <= MAX_DATA_DEPTH:
        return _bounded_data(item, depth)
    if isinstance(item, (list, tuple)) and depth <= MAX_DATA_DEPTH:
        return [_bounded_value(child, depth + 1) for child in item[:MAX_DATA_ENTRIES]]
    return None
