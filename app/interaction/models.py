"""Typed bounded context and interaction lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Sensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    UNKNOWN = "unknown"


class ContextKind(StrEnum):
    SESSION = "session"
    USER_TURN = "user_turn"
    RESPONSE = "response"
    APPLICATION = "application"
    WINDOW = "window"
    DOCUMENT = "document"
    SCREEN = "screen"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    WORKFLOW = "workflow"


class TaskStatus(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SpeechMode(StrEnum):
    SILENT = "silent"
    SHORT = "short"
    NORMAL = "normal"
    DETAILED = "detailed"
    CONFIRMATION = "confirmation"
    ERROR = "error"


class AuthorityStage(StrEnum):
    USER_INTENT = "user_intent"
    MODEL_INTERPRETATION = "model_interpretation"
    TOOL_PROPOSAL = "tool_proposal"
    POLICY_DECISION = "policy_decision"
    USER_CONFIRMATION = "user_confirmation"
    EXECUTION = "execution"


class IntentKind(StrEnum):
    APPLICATION_OPEN = "application.open"
    FILESYSTEM_INSPECT = "filesystem.inspect"
    SYSTEM_OBSERVE = "system.observe"
    AUTOMATION_REQUEST = "automation.request"
    CONTEXT_OPEN = "context.open"
    CONTEXT_READ = "context.read"
    CONTEXT_CLOSE = "context.close"
    CONTEXT_EXPLAIN = "context.explain"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContextItem:
    kind: ContextKind
    content: Any
    source: str
    confidence: float | None = None
    lifetime_seconds: float = 300
    sensitivity: Sensitivity = Sensitivity.UNKNOWN
    identifier: str = field(default_factory=lambda: uuid4().hex)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def expires_at(self) -> datetime:
        return self.observed_at + timedelta(seconds=self.lifetime_seconds)

    def is_fresh(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) < self.expires_at


@dataclass
class TaskContext:
    operation: str
    lifetime_seconds: float = 900
    task_id: str = field(default_factory=lambda: uuid4().hex)
    status: TaskStatus = TaskStatus.NEW
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.lifetime_seconds)

    def refresh_status(self, now: datetime | None = None) -> TaskStatus:
        if self.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.EXPIRED} and (now or datetime.now(timezone.utc)) >= self.expires_at:
            self.status = TaskStatus.EXPIRED
            self.updated_at = now or datetime.now(timezone.utc)
        return self.status


@dataclass(frozen=True)
class ConfirmationContext:
    operation_id: str
    arguments: dict[str, Any]
    session_id: str
    policy_binding: str
    lifetime_seconds: float = 300
    confirmation_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consumed: bool = False

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.lifetime_seconds)


@dataclass(frozen=True)
class ReferenceResult:
    status: str
    item: ContextItem | None = None
    candidates: tuple[ContextItem, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    raw_text: str
    parameters: dict[str, str] = field(default_factory=dict)
    requires_confirmation: bool = False
