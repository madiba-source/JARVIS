"""Central canonical sanitization for every observability sink."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

REDACTED_PLACEHOLDER = "[REDACTED_SENSITIVE_CONTENT]"
CYCLE_PLACEHOLDER = "[CIRCULAR_REFERENCE]"
SENSITIVE_KEY = re.compile(r"password|passwd|token|secret|api[_-]?key|private[_-]?key|authorization|cookie|credential|private", re.I)
CREDENTIAL_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_.-]{12,}|ghp_[A-Za-z0-9]{20,})", re.I)


def _string(value: str) -> str:
    return CREDENTIAL_VALUE.sub(REDACTED_PLACEHOLDER, value)


def redact_sensitive_data(data: Any, *, max_depth: int = 8, max_bytes: int = 64 * 1024) -> Any:
    seen: set[int] = set()
    truncated = False

    def visit(value: Any, depth: int) -> Any:
        nonlocal truncated
        if depth > max_depth:
            truncated = True
            return "[MAX_METADATA_DEPTH]"
        if value is None or isinstance(value, (bool, int, str)):
            return _string(value) if isinstance(value, str) else value
        if isinstance(value, float):
            if not math.isfinite(value):
                return "[NON_FINITE_NUMBER]"
            return value
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in seen:
                return CYCLE_PLACEHOLDER
            seen.add(identity)
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    result[f"[UNSUPPORTED_KEY:{type(key).__name__}]"] = "[UNSUPPORTED_KEY]"
                elif SENSITIVE_KEY.search(key):
                    result[key] = REDACTED_PLACEHOLDER
                else:
                    result[key] = visit(item, depth + 1)
            seen.remove(identity)
            return result
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in seen:
                return CYCLE_PLACEHOLDER
            seen.add(identity)
            result = [visit(item, depth + 1) for item in value]
            seen.remove(identity)
            return result
        return f"[UNSUPPORTED_TYPE:{type(value).__name__}]"

    result = visit(data, 0)
    if truncated:
        result = {"value": result, "_sanitization_truncated": True}
    return result
