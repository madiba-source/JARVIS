"""Optional cloud model provider.

Cloud routing is never required and is never automatic. This provider exists so
that a future configuration can opt in explicitly. It is unconfigured by
default: it holds no endpoint and no credential unless the caller supplies both,
it never reads or invents secrets, and it reports `unavailable` rather than
attempting a call when unconfigured.
"""

from __future__ import annotations

import time
from typing import Any

from .model import ModelRequest, ModelResponse, ModelResponseState, failed_response, ok_response

REQUEST_TIMEOUT_FLOOR = 0.1
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class CloudProvider:
    """OpenAI-compatible HTTP transport. Unconfigured means unavailable."""

    def __init__(self, endpoint: str = "", api_key: str = "", model: str = "",
                 *, name: str = "cloud") -> None:
        self.name = name
        self.endpoint = str(endpoint).strip()
        self._api_key = str(api_key)
        self.model = str(model).strip()

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self._api_key and self.model)

    def available(self) -> bool:
        return self.configured

    def generate(self, request: ModelRequest, cancel: Any = None) -> ModelResponse:
        if not self.configured:
            return failed_response(ModelResponseState.UNAVAILABLE, self.name,
                                   "cloud provider is not configured")
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled before dispatch")
        try:
            import httpx
        except Exception:
            return failed_response(ModelResponseState.UNAVAILABLE, self.name, "http client unavailable")
        started = time.monotonic()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": int(request.max_output_tokens),
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=max(REQUEST_TIMEOUT_FLOOR, request.timeout)) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
        except Exception as error:
            state = ModelResponseState.TIMEOUT if _is_timeout(error) else ModelResponseState.UNAVAILABLE
            return failed_response(state, self.name, type(error).__name__)
        duration = (time.monotonic() - started) * 1000
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled during request")
        if response.status_code in _RETRYABLE_STATUS:
            return failed_response(ModelResponseState.RATE_LIMITED, self.name,
                                   "provider throttled the request")
        if response.status_code >= 400:
            return failed_response(ModelResponseState.REJECTED, self.name,
                                   "provider rejected the request")
        text = _extract_text(response)
        if not text:
            return failed_response(ModelResponseState.REJECTED, self.name, "empty provider response")
        return ok_response(text, self.name, self.model, tokens=0, duration_ms=duration)

    def describe(self) -> dict[str, Any]:
        # The credential is never included, not even in redacted form.
        return {"provider": self.name, "configured": self.configured, "model": self.model}

    def close(self) -> None:
        self._api_key = ""


def _extract_text(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _is_timeout(error: Exception) -> bool:
    return "timeout" in type(error).__name__.lower() or "timed out" in str(error).lower()
