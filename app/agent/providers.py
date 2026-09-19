"""Local-first model providers.

`OllamaProvider` is the real local transport. It is written so that a missing
server, a missing model, a version mismatch or a slow reply all become a typed
failure state rather than an exception, because the runtime must stay usable
offline.

`StaticProvider` is the deterministic simulation adapter used by tests and by
dry-run style verification. It never touches the network or the filesystem.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .model import ModelRequest, ModelResponse, ModelResponseState, failed_response, ok_response

PROBE_TTL_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 1.5


class UnavailableProvider:
    """Reports unavailability for every request. The safe default."""

    def __init__(self, reason: str = "no local model configured", name: str = "unavailable") -> None:
        self.name = name
        self._reason = reason

    def available(self) -> bool:
        return False

    def generate(self, request: ModelRequest, cancel: Any = None) -> ModelResponse:
        return failed_response(ModelResponseState.UNAVAILABLE, self.name, self._reason)

    def close(self) -> None:
        return None


class StaticProvider:
    """Deterministic scripted provider for tests and simulation."""

    def __init__(self, responses: tuple[str, ...] | list[str] = (), *, name: str = "static",
                 model_name: str = "static-model", failures: tuple[ModelResponseState, ...] = (),
                 delay: float = 0.0, block: threading.Event | None = None) -> None:
        self.name = name
        self.model_name = model_name
        self._responses = list(responses)
        self._failures = list(failures)
        self._delay = max(0.0, float(delay))
        self._block = block
        self._index = 0
        self._lock = threading.Lock()
        self.calls = 0

    def available(self) -> bool:
        return True

    def _next_text(self) -> str:
        with self._lock:
            if not self._responses:
                return ""
            if self._index < len(self._responses):
                value = self._responses[self._index]
            else:
                value = self._responses[-1]
            self._index += 1
            return value

    def generate(self, request: ModelRequest, cancel: Any = None) -> ModelResponse:
        with self._lock:
            self.calls += 1
            failure = self._failures.pop(0) if self._failures else None
        if self._block is not None and not self._block.wait(timeout=request.timeout):
            return failed_response(ModelResponseState.TIMEOUT, self.name, "scripted wait expired")
        if self._delay:
            self._sleep_with_cancel(request.timeout, cancel)
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled")
        if failure is not None and failure is not ModelResponseState.OK:
            return failed_response(failure, self.name, "scripted provider failure")
        text = self._next_text()
        if not text:
            return failed_response(ModelResponseState.UNAVAILABLE, self.name, "script exhausted")
        tokens = max(1, len(text) // 4)
        return ok_response(text, self.name, self.model_name, tokens=tokens, duration_ms=self._delay * 1000)

    def _sleep_with_cancel(self, timeout: float, cancel: Any) -> None:
        deadline = time.monotonic() + min(self._delay, timeout)
        while time.monotonic() < deadline:
            if cancel is not None and getattr(cancel, "is_cancelled", False):
                return
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    def close(self) -> None:
        return None


class OllamaProvider:
    """Local model transport. Fails closed on any transport problem."""

    def __init__(self, host: str, model: str, *, name: str = "ollama",
                 probe_ttl: float = PROBE_TTL_SECONDS) -> None:
        self.name = name
        self.model = str(model)
        self.host = str(host)
        self._probe_ttl = max(0.0, float(probe_ttl))
        self._probe_at = 0.0
        self._probe_result = False
        self._lock = threading.Lock()

    def _client(self, timeout: float) -> Any:
        import ollama  # imported lazily so the runtime works without it

        return ollama.Client(host=self.host, timeout=timeout)

    def available(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._probe_at < self._probe_ttl:
                return self._probe_result
        result = self._probe()
        with self._lock:
            self._probe_at = time.monotonic()
            self._probe_result = result
            return result

    def _probe(self) -> bool:
        try:
            client = self._client(PROBE_TIMEOUT_SECONDS)
            client.list()
            return True
        except Exception:
            return False

    def generate(self, request: ModelRequest, cancel: Any = None) -> ModelResponse:
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled before dispatch")
        started = time.monotonic()
        try:
            client = self._client(request.timeout)
            result = client.generate(
                model=self.model,
                prompt=request.prompt,
                options={"num_predict": int(request.max_output_tokens), "temperature": 0.0},
            )
        except Exception as error:
            state = ModelResponseState.TIMEOUT if _looks_like_timeout(error) else ModelResponseState.UNAVAILABLE
            return failed_response(state, self.name, type(error).__name__)
        duration = (time.monotonic() - started) * 1000
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled during generation")
        text = _field(result, "response")
        if not isinstance(text, str) or not text:
            return failed_response(ModelResponseState.REJECTED, self.name, "empty model output")
        tokens = _field(result, "eval_count")
        model_name = _field(result, "model")
        return ok_response(text, self.name, str(model_name or self.model),
                           tokens=tokens if isinstance(tokens, int) else 0, duration_ms=duration)

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "available": self.available()}

    def close(self) -> None:
        return None


def _field(result: Any, key: str) -> Any:
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key, None)


def _looks_like_timeout(error: Exception) -> bool:
    name = type(error).__name__.lower()
    return "timeout" in name or "timed out" in str(error).lower()
