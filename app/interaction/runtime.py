"""Turn orchestration with cooperative cancellation and resource bounds."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

from app.agent.cancel import CancellationToken
from app.policy.confirmation import ConfirmationManager
from app.policy.enums import AuthorizationLevel

from .models import ConfirmationContext, ContextKind, Intent, IntentKind, SpeechMode
from .normalizer import normalize_intent
from .state import ConversationState


@dataclass(frozen=True)
class TurnResult:
    intent: Intent
    speech_mode: SpeechMode
    response: str
    cancelled: bool = False
    untrusted: bool = False


class InteractionRuntime:
    def __init__(self, *, state: ConversationState | None = None, max_concurrent: int = 1, max_response_chars: int = 4000) -> None:
        if max_concurrent <= 0 or max_response_chars <= 0:
            raise ValueError("interaction limits must be positive")
        self.state = state or ConversationState()
        self.max_response_chars = max_response_chars
        self._enabled = True
        self._active: CancellationToken | None = None
        self._lock = threading.Lock()
        self._speech_stop: Callable[[], None] | None = None
        self.max_concurrent = max_concurrent
        self.confirmation_manager: ConfirmationManager | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def disable(self) -> None:
        self._enabled = False
        self.cancel("disabled")
        if self._speech_stop is not None:
            self._speech_stop()
            self._speech_stop = None

    def enable(self) -> None:
        self._enabled = True

    def begin_speech(self, stop_speech: Callable[[], None]) -> CancellationToken:
        if not self._enabled:
            return CancellationToken.cancelled("disabled")
        if self._speech_stop is not None:
            self._speech_stop()
        self._speech_stop = stop_speech
        self.cancel("barge-in")
        token = CancellationToken("voice turn")
        with self._lock:
            self._active = token
        return token

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            token = self._active
        if token is not None:
            token.cancel(reason)

    def request_confirmation(self, *, tool_id: str, request_id: str, operation: str, arguments: dict, authorization_level: AuthorizationLevel, effective_budget: dict[str, float], policy_binding: str) -> str:
        if self.confirmation_manager is None:
            self.confirmation_manager = ConfirmationManager()
        token = self.confirmation_manager.generate_token(tool_id=tool_id, request_id=request_id, operation=operation, arguments=arguments, authorization_level=authorization_level, effective_budget=effective_budget)
        self.state.set_confirmation(ConfirmationContext(request_id, arguments.copy(), self.state.session_id, policy_binding, confirmation_id=token))
        return token

    def confirm(self, token: str, *, tool_id: str, request_id: str, operation: str, arguments: dict, authorization_level: AuthorizationLevel, effective_budget: dict[str, float], policy_binding: str) -> bool:
        manager = self.confirmation_manager
        if manager is None or not manager.validate_and_consume(token, tool_id=tool_id, request_id=request_id, operation=operation, arguments=arguments, authorization_level=authorization_level, effective_budget=effective_budget):
            return False
        return self.state.consume_confirmation(token, operation_id=request_id, arguments=arguments, session_id=self.state.session_id, policy_binding=policy_binding)

    def submit(self, text: str, *, response: str | None = None, token: CancellationToken | None = None) -> TurnResult:
        if not self._enabled:
            return TurnResult(Intent(normalize_intent(text).kind, text), SpeechMode.ERROR, "JARVIS is disabled.", cancelled=True)
        active = token or CancellationToken()
        active.raise_if_cancelled()
        intent = normalize_intent(text)
        self.state.add_turn(text, user=True)
        untrusted = _contains_instruction(text)
        if response is None:
            result_text = self._default_response(intent)
        else:
            result_text = response[:self.max_response_chars]
        mode = self.classify_speech(intent, result_text)
        self.state.add_turn(result_text, user=False)
        return TurnResult(intent, mode, result_text, untrusted=untrusted)

    @staticmethod
    def classify_speech(intent: Intent, response: str) -> SpeechMode:
        if not response:
            return SpeechMode.SILENT
        if intent.requires_confirmation:
            return SpeechMode.CONFIRMATION
        if intent.kind == IntentKind.UNKNOWN:
            return SpeechMode.ERROR
        if len(response) <= 120:
            return SpeechMode.SHORT
        if len(response) > 600:
            return SpeechMode.DETAILED
        return SpeechMode.NORMAL

    def _default_response(self, intent: Intent) -> str:
        if intent.kind == IntentKind.UNKNOWN:
            return "I could not determine the requested operation."
        if intent.kind == IntentKind.AUTOMATION_REQUEST and not intent.parameters.get("schedule"):
            return "What should I remind you about, and when?"
        if intent.kind.name.startswith("CONTEXT_"):
            reference = self.state.resolve_reference("it")
            if reference.status == "ambiguous":
                return reference.message
            if reference.status != "resolved":
                return "I could not find a current reference for that."
        return f"I understood this as {intent.kind.value}."


def _contains_instruction(text: str) -> bool:
    return bool(re.search(r"ignore\s+(?:all\s+)?previous|system\s+message|execute\s+this|override\s+safety", text, re.IGNORECASE))
