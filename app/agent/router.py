"""Local-first model routing.

Routing order is fixed and deliberate:

    LOCAL -> (only if configured and permitted) CLOUD

Cloud routing requires `cloud_enabled` in configuration *and* a configured
provider. There is no automatic fallback to cloud, no credential collection and
no mandatory network dependency: with `cloud_enabled = False` the runtime is
fully functional using local inference only.

Only one local inference runs at a time. That is a real constraint of the target
hardware, so it is enforced by a semaphore rather than assumed.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .config import AgentConfig, PrivacyMode
from .errors import AgentConfigurationError
from .model import ModelRequest, ModelResponse, ModelResponseState, failed_response
from .providers import UnavailableProvider

LOCAL_FALLBACK_STATES = frozenset({ModelResponseState.UNAVAILABLE})
_FALLBACK_PROVIDER = "router"
_SENSITIVE_RE = re.compile(r"\b(secret|password|token|api[_ -]?key|credential|private key|ssh|passwd|authorization)\b", re.I)


class ModelRouter:
    """Deterministic provider selection with bounded concurrency."""

    def __init__(self, config: AgentConfig, local: Any = None, cloud: Any = None) -> None:
        if config.max_parallel_model_calls != 1:
            raise AgentConfigurationError("local inference concurrency must remain one")
        self._config = config
        self._local = local or UnavailableProvider()
        self._cloud = cloud if config.cloud_enabled else None
        self._gate = threading.BoundedSemaphore(config.max_parallel_model_calls)
        self._lock = threading.RLock()
        self.calls = 0
        self.cloud_calls = 0

    @property
    def local(self) -> Any:
        return self._local

    @property
    def cloud_enabled(self) -> bool:
        if not self._config.cloud_enabled or self._cloud is None:
            return False
        if self._config.privacy_mode is PrivacyMode.OFFLINE_ONLY:
            return False
        return True

    def local_available(self) -> bool:
        try:
            return bool(self._local.available())
        except Exception:
            return False

    def cloud_available(self) -> bool:
        if not self.cloud_enabled:
            return False
        try:
            return bool(self._cloud.available())
        except Exception:
            return False

    def available(self) -> bool:
        return self.local_available() or self.cloud_available()

    def describe(self) -> dict[str, Any]:
        return {
            "local": getattr(self._local, "name", "local"),
            "local_available": self.local_available(),
            "cloud_enabled": self.cloud_enabled,
            "cloud_available": self.cloud_available(),
            "calls": self.calls,
        }

    def generate(self, request: ModelRequest, cancel: Any = None) -> ModelResponse:
        """Run one bounded model call. Never raises; failure is a state."""
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, _FALLBACK_PROVIDER,
                                   "cancelled before dispatch")
        if not self._gate.acquire(blocking=True, timeout=request.timeout):
            return failed_response(ModelResponseState.UNAVAILABLE, _FALLBACK_PROVIDER,
                                   "model concurrency limit reached")
        try:
            return self._generate_locked(request, cancel)
        finally:
            self._gate.release()

    def _cloud_allowed(self, request: ModelRequest) -> bool:
        if not self.cloud_enabled:
            return False
        if self._config.privacy_mode is PrivacyMode.OFFLINE_ONLY:
            return False
        if self._config.privacy_mode is PrivacyMode.LOCAL_PREFERRED and _SENSITIVE_RE.search(request.prompt):
            return False
        return True

    def _generate_locked(self, request: ModelRequest, cancel: Any) -> ModelResponse:
        with self._lock:
            self.calls += 1
        response = self._attempt(self._local, request, cancel)
        if response.ok or response.state is ModelResponseState.CANCELLED:
            return response
        if not self._cloud_allowed(request) or response.state not in LOCAL_FALLBACK_STATES:
            return response
        if cancel is not None and getattr(cancel, "is_cancelled", False):
            return failed_response(ModelResponseState.CANCELLED, _FALLBACK_PROVIDER,
                                   "cancelled before cloud fallback")
        with self._lock:
            self.cloud_calls += 1
        cloud_response = self._attempt(self._cloud, request, cancel)
        return cloud_response if cloud_response.ok else response

    def _attempt(self, provider: Any, request: ModelRequest, cancel: Any) -> ModelResponse:
        provider_name = getattr(provider, "name", "model")
        attempts = max(1, int(self._config.max_model_attempts))
        last: ModelResponse | None = None
        for attempt in range(attempts):
            if cancel is not None and getattr(cancel, "is_cancelled", False):
                return failed_response(ModelResponseState.CANCELLED, provider_name,
                                       "cancelled before attempt")
            try:
                result = provider.generate(request, cancel)
            except Exception as error:
                result = failed_response(ModelResponseState.UNAVAILABLE, provider_name,
                                         type(error).__name__)
            if not isinstance(result, ModelResponse):
                return failed_response(ModelResponseState.REJECTED, provider_name,
                                       "malformed provider response")
            if result.ok or result.state is ModelResponseState.CANCELLED:
                return result
            last = result
            if attempt + 1 < attempts and result.state in LOCAL_FALLBACK_STATES:
                continue
            break
        return last or failed_response(ModelResponseState.UNAVAILABLE, provider_name, "no response")

    def close(self) -> None:
        for provider in (self._local, self._cloud):
            closer = getattr(provider, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    continue
