"""Optional cloud model provider.

Cloud routing is never required and is never automatic. This provider exists so
that a future configuration can opt in explicitly. It is unconfigured by
default: it holds no endpoint and no credential unless the caller supplies both,
it never reads or invents secrets, and it reports `unavailable` rather than
attempting a call when unconfigured.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

from .model import ModelRequest, ModelResponse, ModelResponseState, failed_response, ok_response

REQUEST_TIMEOUT_FLOOR = 0.1
MAX_CLOUD_PAYLOAD_BYTES = 64 * 1024
MAX_CLOUD_RESPONSE_BYTES = 64 * 1024
MAX_CLOUD_CONCURRENT_REQUESTS = 1
MAX_CLOUD_RETRIES = 2
MAX_CLOUD_BACKOFF_SECONDS = 0.25
_SENSITIVE_RE = re.compile(
    r"\b(secret|password|token|api[_ -]?key|credential|private key|ssh|passwd|authorization)\b",
    re.I,
)
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class CloudProvider:
    """OpenAI-compatible HTTP transport. Unconfigured means unavailable."""

    def __init__(self, endpoint: str = "", api_key: str = "", model: str = "",
                 *, name: str = "cloud") -> None:
        self.name = name
        self.endpoint = str(endpoint).strip()
        self._api_key = str(api_key)
        self.model = str(model).strip()
        self._gate = threading.BoundedSemaphore(MAX_CLOUD_CONCURRENT_REQUESTS)

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self._api_key and self.model)

    def validate_request(self, endpoint: str, payload: Any) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("cloud endpoint must be a valid http(s) URL")
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_CLOUD_PAYLOAD_BYTES:
            raise ValueError("cloud payload exceeds bounded size")
        content = payload.get("messages", [{}])[0].get("content", "") if isinstance(payload, dict) else ""
        if isinstance(content, str) and _SENSITIVE_RE.search(content):
            raise ValueError("cloud payload contains sensitive content")

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
        try:
            self.validate_request(self.endpoint, payload)
        except ValueError as error:
            return failed_response(ModelResponseState.REJECTED, self.name, str(error))
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if not self._gate.acquire(blocking=False):
            return failed_response(ModelResponseState.UNAVAILABLE, self.name,
                                   "cloud concurrency limit reached")
        try:
            response = None
            for attempt in range(MAX_CLOUD_RETRIES + 1):
                try:
                    with httpx.Client(timeout=max(REQUEST_TIMEOUT_FLOOR, request.timeout)) as client:
                        response = client.post(self.endpoint, json=payload, headers=headers)
                except Exception as error:
                    state = ModelResponseState.TIMEOUT if _is_timeout(error) else ModelResponseState.UNAVAILABLE
                    return failed_response(state, self.name, type(error).__name__)
                if response.status_code not in _RETRYABLE_STATUS or attempt >= MAX_CLOUD_RETRIES:
                    break
                time.sleep(min(MAX_CLOUD_BACKOFF_SECONDS, 0.05 * (2 ** attempt)))
        finally:
            self._gate.release()
        if response is None:
            return failed_response(ModelResponseState.UNAVAILABLE, self.name, "no provider response")
        duration = (time.monotonic() - started) * 1000
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, self.name, "cancelled during request")
        if response.status_code in _RETRYABLE_STATUS:
            return failed_response(ModelResponseState.RATE_LIMITED, self.name,
                                   "provider throttled the request")
        if response.status_code >= 400:
            return failed_response(ModelResponseState.REJECTED, self.name,
                                   "provider rejected the request")
        if len(response.content) > MAX_CLOUD_RESPONSE_BYTES:
            return failed_response(ModelResponseState.OVERSIZED, self.name,
                                   "cloud response exceeds bounded size")
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
