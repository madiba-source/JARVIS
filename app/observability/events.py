"""Immutable, bounded structured event records."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import EventType, Severity
from .ids import generate_event_id


class FrozenMap(Mapping[str, Any]):
    def __init__(self, items: tuple[tuple[str, Any], ...]) -> None:
        self._items = items
        self._data = dict(items)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)


def _freeze(value: Any, depth: int = 0, max_depth: int = 8, seen: set[int] | None = None) -> Any:
    seen = seen or set()
    if depth > max_depth:
        return "[MAX_METADATA_DEPTH]"
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            return "[CIRCULAR_REFERENCE]"
        seen.add(identity)
        result = FrozenMap(tuple((key, _freeze(item, depth + 1, max_depth, seen)) for key, item in value.items() if isinstance(key, str)))
        seen.remove(identity)
        return result
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            return "[CIRCULAR_REFERENCE]"
        seen.add(identity)
        result = tuple(_freeze(item, depth + 1, max_depth, seen) for item in value)
        seen.remove(identity)
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"[UNSUPPORTED_TYPE:{type(value).__name__}]"


class StructuredEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    event_id: str = Field(default_factory=generate_event_id, min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    monotonic_timestamp: float = Field(default_factory=time.monotonic)
    event_type: EventType
    severity: Severity = Severity.INFO
    component: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=256)
    request_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=64)
    span_id: str | None = Field(default=None, max_length=64)
    operation: str | None = Field(default=None, max_length=128)
    authorization_level: str | None = Field(default=None, max_length=32)
    tool_id: str | None = Field(default=None, max_length=128)
    duration_ms: float | None = Field(default=None, ge=0)
    success: bool | None = None
    error_type: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=2048)
    metadata: FrozenMap = Field(default_factory=lambda: FrozenMap(()))

    @field_validator("metadata", mode="before")
    @classmethod
    def freeze_metadata(cls, value: Any) -> FrozenMap:
        frozen = _freeze(value or {})
        return frozen if isinstance(frozen, FrozenMap) else FrozenMap((("value", frozen),))
