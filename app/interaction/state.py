"""Bounded short-term conversation and task state."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .models import ConfirmationContext, ContextItem, ContextKind, ReferenceResult, TaskContext, TaskStatus


class ConversationState:
    def __init__(self, *, session_id: str | None = None, max_turns: int = 20, max_items: int = 64, max_tokens: int = 8000) -> None:
        if min(max_turns, max_items, max_tokens) <= 0:
            raise ValueError("conversation limits must be positive")
        self.session_id = session_id or uuid4().hex
        self.max_turns = max_turns
        self.max_items = max_items
        self.max_tokens = max_tokens
        self._items: deque[ContextItem] = deque(maxlen=max_items)
        self._turns: deque[ContextItem] = deque(maxlen=max_turns)
        self.active_task: TaskContext | None = None
        self.pending_confirmation: ConfirmationContext | None = None

    @property
    def items(self) -> tuple[ContextItem, ...]:
        self._expire()
        return tuple(self._items)

    @property
    def turns(self) -> tuple[ContextItem, ...]:
        self._expire()
        return tuple(self._turns)

    def add_turn(self, text: str, *, user: bool, sensitivity: Any = None) -> ContextItem:
        item = self.add_item(ContextKind.USER_TURN if user else ContextKind.RESPONSE, text, source="user" if user else "jarvis", sensitivity=sensitivity)
        self._turns.append(item)
        self._trim_tokens()
        return item

    def add_item(self, kind: ContextKind, content: Any, *, source: str, confidence: float | None = None, lifetime_seconds: float = 300, sensitivity: Any = None) -> ContextItem:
        item = ContextItem(kind=kind, content=content, source=source, confidence=confidence, lifetime_seconds=lifetime_seconds, sensitivity=sensitivity or "unknown")
        self._items.append(item)
        self._expire()
        return item

    def add_screen_observation(self, observation: Any) -> ContextItem:
        return self.add_item(ContextKind.SCREEN, observation, source="vision", confidence=getattr(observation, "confidence", None), lifetime_seconds=getattr(observation, "lifetime_seconds", 300), sensitivity="unknown")

    def begin_task(self, operation: str, *, lifetime_seconds: float = 900, **details: Any) -> TaskContext:
        self.active_task = TaskContext(operation=operation, lifetime_seconds=lifetime_seconds, details=details, status=TaskStatus.ACTIVE)
        return self.active_task

    def expire_task(self) -> None:
        if self.active_task is not None:
            self.active_task.refresh_status(datetime.now(timezone.utc))

    def set_confirmation(self, confirmation: ConfirmationContext) -> None:
        self.pending_confirmation = confirmation
        if self.active_task is not None:
            self.active_task.status = TaskStatus.WAITING_FOR_CONFIRMATION

    def consume_confirmation(self, confirmation_id: str, *, operation_id: str, arguments: dict[str, Any], session_id: str, policy_binding: str) -> bool:
        confirmation = self.pending_confirmation
        now = datetime.now(timezone.utc)
        if confirmation is None or confirmation.confirmation_id != confirmation_id or confirmation.session_id != session_id or confirmation.operation_id != operation_id or confirmation.policy_binding != policy_binding or confirmation.expires_at <= now or confirmation.consumed or confirmation.arguments != arguments:
            return False
        self.pending_confirmation = ConfirmationContext(**{**confirmation.__dict__, "consumed": True})
        return True

    def resolve_reference(self, phrase: str, *, kind: ContextKind | None = None) -> ReferenceResult:
        self._expire()
        normalized = phrase.casefold().strip()
        candidates = [item for item in reversed(self._items) if kind is None or item.kind == kind]
        if normalized in {"that", "this", "it", "the thing", "the document", "the window"}:
            if normalized in {"the document"}:
                candidates = [item for item in candidates if item.kind == ContextKind.DOCUMENT]
            elif normalized in {"the window"}:
                candidates = [item for item in candidates if item.kind == ContextKind.WINDOW]
            if not candidates:
                return ReferenceResult("not_found", message="No current context matches that reference.")
            if len(candidates) > 1 and normalized in {"that", "it", "this"}:
                return ReferenceResult("ambiguous", candidates=tuple(candidates), message="Which item do you mean?")
            return ReferenceResult("resolved", item=candidates[0])
        return ReferenceResult("not_found", message="Reference is not recognized.")

    def _expire(self) -> None:
        now = datetime.now(timezone.utc)
        self._items = deque((item for item in self._items if item.is_fresh(now)), maxlen=self.max_items)
        self._turns = deque((item for item in self._turns if item.is_fresh(now)), maxlen=self.max_turns)
        self.expire_task()

    def _trim_tokens(self) -> None:
        while sum(len(str(item.content)) for item in self._turns) > self.max_tokens and self._turns:
            self._turns.popleft()
