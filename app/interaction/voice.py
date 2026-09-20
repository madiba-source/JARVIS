"""Bounded local voice turn and speech interruption controls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.agent.cancel import CancellationToken


class VoiceTurnDetector:
    def __init__(self, *, max_seconds: float = 30, silence_seconds: float = 1.2, push_to_talk: bool = True) -> None:
        if max_seconds <= 0 or silence_seconds <= 0:
            raise ValueError("voice limits must be positive")
        self.max_seconds = max_seconds
        self.silence_seconds = silence_seconds
        self.push_to_talk = push_to_talk

    def capture(self, read_chunk: Callable[[], tuple[str, bool]], *, token: CancellationToken | None = None) -> str:
        active = token or CancellationToken()
        started = time.monotonic()
        chunks: list[str] = []
        silent_since: float | None = None
        silent_chunks = 0
        while time.monotonic() - started < self.max_seconds:
            active.raise_if_cancelled()
            text, has_voice = read_chunk()
            if text:
                chunks.append(text)
            if has_voice:
                silent_since = None
                silent_chunks = 0
            elif chunks:
                silent_chunks += 1
                silent_since = silent_since or time.monotonic()
                if silent_chunks >= 2 or time.monotonic() - silent_since >= self.silence_seconds:
                    break
        return " ".join(chunks).strip()


class SpeechController:
    def __init__(self, speak_backend: Callable[[str, CancellationToken], None]) -> None:
        self._backend = speak_backend
        self._token: CancellationToken | None = None
        self._lock = threading.Lock()

    def speak(self, text: str) -> CancellationToken:
        self.stop()
        token = CancellationToken("speech")
        with self._lock:
            self._token = token
        self._backend(text, token)
        return token

    def stop(self) -> None:
        with self._lock:
            token = self._token
        if token is not None:
            token.cancel("speech interrupted")
