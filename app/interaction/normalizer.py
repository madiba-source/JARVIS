"""Deterministic natural-language to typed-intent normalization."""

from __future__ import annotations

import re

from .models import Intent, IntentKind


def normalize_intent(text: str) -> Intent:
    raw = text.strip()
    lowered = raw.casefold()
    if not raw:
        return Intent(IntentKind.UNKNOWN, raw)
    match = re.search(r"\bopen\s+(?:the\s+)?(.+?)[.!?]*$", lowered)
    if match and not any(word in lowered for word in ("file", "document", "it", "that", "this")):
        return Intent(IntentKind.APPLICATION_OPEN, raw, {"application": match.group(1).strip()})
    if any(term in lowered for term in ("whether the file exists", "check if the file", "does the file exist", "file exists")):
        return Intent(IntentKind.FILESYSTEM_INSPECT, raw, {"target": _target(raw)})
    if "using cpu" in lowered or "cpu usage" in lowered or "system" in lowered and "show" in lowered:
        return Intent(IntentKind.SYSTEM_OBSERVE, raw, {"observation": "cpu" if "cpu" in lowered else "system"})
    if lowered.startswith("remind me"):
        return Intent(IntentKind.AUTOMATION_REQUEST, raw, {"schedule": raw[len("remind me"):].strip()}, True)
    if lowered.startswith(("open that", "open it", "go back to")):
        return Intent(IntentKind.CONTEXT_OPEN, raw)
    if lowered.startswith(("read this", "read that", "read it")):
        return Intent(IntentKind.CONTEXT_READ, raw)
    if lowered.startswith(("close that", "close it", "close the window")):
        return Intent(IntentKind.CONTEXT_CLOSE, raw, requires_confirmation=False)
    if lowered.startswith(("what does this", "what is this", "explain this", "explain that")):
        return Intent(IntentKind.CONTEXT_EXPLAIN, raw)
    return Intent(IntentKind.UNKNOWN, raw)


def _target(text: str) -> str:
    match = re.search(r"(?:file|path)\s+([^.!?]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""
