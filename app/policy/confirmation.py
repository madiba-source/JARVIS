"""Strict, action-bound, single-use confirmation tokens with bounded storage."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict

from .enums import AuthorizationLevel


class ConfirmationToken(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    tool_id: str
    request_id: str
    operation: str
    action_hash: str
    expires_at: datetime
    consumed: bool = False


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not canonical JSON")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    raise ValueError(f"unsupported canonical JSON value: {type(value).__name__}")


class ConfirmationManager:
    def __init__(self, token_ttl_seconds: int = 300, max_tokens: int = 1024, clock: Callable[[], datetime] | None = None) -> None:
        if token_ttl_seconds <= 0 or max_tokens <= 0:
            raise ValueError("confirmation limits must be positive")
        self._ttl = token_ttl_seconds
        self._max_tokens = max_tokens
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._tokens: dict[str, ConfirmationToken] = {}
        self._lock = threading.Lock()

    @staticmethod
    def compute_action_hash(tool_id: str, request_id: str, operation: str, arguments: Mapping[str, Any], authorization_level: AuthorizationLevel, effective_budget: Mapping[str, float]) -> str:
        data = _canonical({
            "tool_id": tool_id, "request_id": request_id, "operation": operation,
            "arguments": arguments, "authorization_level": int(authorization_level),
            "effective_resource_constraints": effective_budget,
        })
        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _prune_locked(self, now: datetime) -> None:
        expired = [key for key, value in self._tokens.items() if value.expires_at <= now or value.consumed]
        for key in expired:
            self._tokens.pop(key, None)
        while len(self._tokens) >= self._max_tokens:
            oldest = min(self._tokens, key=lambda key: self._tokens[key].expires_at)
            self._tokens.pop(oldest, None)

    def generate_token(self, *, tool_id: str, request_id: str, operation: str, arguments: Mapping[str, Any], authorization_level: AuthorizationLevel, effective_budget: Mapping[str, float]) -> str:
        action_hash = self.compute_action_hash(tool_id, request_id, operation, arguments, authorization_level, effective_budget)
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            token = f"jarvis_cfm_{secrets.token_urlsafe(32)}"
            self._tokens[token] = ConfirmationToken(token=token, tool_id=tool_id, request_id=request_id, operation=operation, action_hash=action_hash, expires_at=now + timedelta(seconds=self._ttl))
            return token

    def validate_and_consume(self, token: str | None, *, tool_id: str, request_id: str, operation: str, arguments: Mapping[str, Any], authorization_level: AuthorizationLevel, effective_budget: Mapping[str, float]) -> bool:
        if not token:
            return False
        expected = self.compute_action_hash(tool_id, request_id, operation, arguments, authorization_level, effective_budget)
        now = self._clock()
        with self._lock:
            self._prune_locked(now)
            record = self._tokens.get(token)
            if record is None or record.expires_at <= now or record.consumed:
                return False
            if (record.tool_id, record.request_id, record.operation, record.action_hash) != (tool_id, request_id, operation, expected):
                return False
            self._tokens[token] = record.model_copy(update={"consumed": True})
            return True

    @property
    def token_count(self) -> int:
        with self._lock:
            self._prune_locked(self._clock())
            return len(self._tokens)
