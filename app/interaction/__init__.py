"""Bounded, policy-aware natural interaction primitives."""

from .models import (
    AuthorityStage,
    ContextItem,
    ContextKind,
    Intent,
    IntentKind,
    ReferenceResult,
    Sensitivity,
    SpeechMode,
    TaskContext,
    TaskStatus,
)
from .normalizer import normalize_intent
from .runtime import InteractionRuntime
from .state import ConversationState
from .voice import SpeechController, VoiceTurnDetector

__all__ = [
    "AuthorityStage",
    "ContextItem",
    "ContextKind",
    "ConversationState",
    "InteractionRuntime",
    "Intent",
    "IntentKind",
    "ReferenceResult",
    "Sensitivity",
    "SpeechMode",
    "TaskContext",
    "TaskStatus",
    "normalize_intent",
    "SpeechController",
    "VoiceTurnDetector",
]
